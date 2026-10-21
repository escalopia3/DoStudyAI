from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time

import httpx

from agent_service.config import Settings
from agent_service.learning_agent.budget import AgentBudget, BudgetExceeded, DeadlineExceeded
from agent_service.learning_agent.gateway.openai_compatible import OpenAiCompatibleLearningGateway
from agent_service.learning_agent.graph import LearningAgentGraph
from agent_service.learning_agent.persistence import AgentRunStore, agent_events
from agent_service.learning_agent.schemas import AgentRunRequest
from agent_service.learning_agent.state import AgentState
from agent_service.store import Store
from knowledge_service.indexing.embedding import LocalBgeM3Config, LocalBgeM3Provider
from knowledge_service.indexing.qdrant import QdrantIndex
from knowledge_service.indexing.retrieval import KnowledgeRetriever
from knowledge_service.indexing.store import IndexStore
from knowledge_service.retrieval.service import EvidenceRetriever
from sqlalchemy import select, update

log=logging.getLogger("learning.agent.worker")


class LearningAgentWorker:
    def __init__(self,settings:Settings,store:AgentRunStore):
        self.settings,self.store=settings,store;self.stopping=False;self._runtime=None
        self.http=httpx.Client(base_url=settings.java_url,timeout=30,
            headers={"Authorization":"Bearer "+settings.token},trust_env=False)

    def runtime(self):
        if self._runtime:return self._runtime
        config=LocalBgeM3Config(model_path=os.environ["LEARNING_EMBEDDING_MODEL_PATH"],
            model_revision=os.environ["LEARNING_EMBEDDING_MODEL_REVISION"],
            dimension=int(os.getenv("LEARNING_EMBEDDING_DIMENSION","1024")),
            batch_size=int(os.getenv("LEARNING_EMBEDDING_BATCH_SIZE","8")),
            device=os.getenv("LEARNING_EMBEDDING_DEVICE","cpu"))
        embedding=LocalBgeM3Provider(config)
        qdrant=QdrantIndex(os.environ["LEARNING_QDRANT_URL"],os.environ["LEARNING_QDRANT_COLLECTION"],
            config.dimension,os.getenv("LEARNING_QDRANT_API_KEY",""))
        retriever=EvidenceRetriever(KnowledgeRetriever(IndexStore(self.settings.database_url),qdrant,embedding))
        gateway=OpenAiCompatibleLearningGateway()
        budget=AgentBudget(max_input_tokens=int(os.getenv("LEARNING_LLM_MAX_INPUT_TOKENS","24000")),
            max_output_tokens=int(os.getenv("LEARNING_LLM_MAX_OUTPUT_TOKENS","1600")))
        graph=LearningAgentGraph(gateway,retriever,budget,cancelled=lambda run:self.cancelled(run))
        self._runtime=(graph,graph.compile(),qdrant,gateway);return self._runtime

    def cancelled(self,run_id):
        row=self.store.get(run_id);return not row or row["state"]=="CANCELLED" or self.stopping

    def callback_once(self):
        with self.store.engine.connect() as db:
            row=db.execute(select(agent_events).where(agent_events.c.delivered==0,
                agent_events.c.available_at<=time.time()).order_by(agent_events.c.available_at,
                agent_events.c.sequence).limit(1)).mappings().first()
        if not row:return False
        try:
            response=self.http.post("/internal/learning/agent-events",json=json.loads(row["payload_json"]));response.raise_for_status();changes={"delivered":1}
        except httpx.HTTPError:
            attempts=row["attempts"]+1;changes={"attempts":attempts,"available_at":time.time()+min(3600,2**min(attempts,12))}
            if attempts>=20:changes["delivered"]=-1
        with self.store.engine.begin() as db:db.execute(update(agent_events).where(agent_events.c.event_id==row["event_id"],agent_events.c.delivered==0).values(**changes))
        return True

    def run_once(self):
        row=self.store.claim(self.settings.lease_seconds,2)
        if not row:return False
        stop=threading.Event();lost=threading.Event()
        def heartbeat():
            while not stop.wait(max(1,self.settings.lease_seconds//3)):
                if not self.store.renew(row["run_id"],row["attempt"],self.settings.lease_seconds):lost.set();return
        thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
        try:
            request=AgentRunRequest.model_validate_json(row["payload_json"]);graph,compiled,_,_=self.runtime()
            output=compiled.invoke(AgentState(request))
            final_state=output if isinstance(output,AgentState) else AgentState(**output)
            if lost.is_set():raise RuntimeError("LEASE_LOST")
            insufficient=bool(final_state.critic and not final_state.critic.passed)
            result=graph.result(final_state,insufficient)
            if not self.store.finish(row["run_id"],row["attempt"],result,"COMPLETED"):raise RuntimeError("LEASE_LOST")
        except DeadlineExceeded as error:self.store.finish(row["run_id"],row["attempt"],None,"TIMED_OUT",str(error)[:64])
        except BudgetExceeded as error:self.store.finish(row["run_id"],row["attempt"],None,"BUDGET_EXCEEDED",str(error)[:64])
        except Exception as error:
            code="RUN_CANCELLED" if self.cancelled(row["run_id"]) else str(error)[:64] or "AGENT_FAILED"
            self.store.finish(row["run_id"],row["attempt"],None,"CANCELLED" if code=="RUN_CANCELLED" else "FAILED",code)
            log.exception("learning_agent_failed runId=%s code=%s",row["run_id"],code)
        finally:stop.set();thread.join(timeout=5)
        return True

    def close(self):
        if self._runtime:self._runtime[2].close();self._runtime[3].close()
        self.http.close()


def main():
    logging.basicConfig(level=logging.INFO);settings=Settings.from_env();base=Store(settings.database_url)
    worker=LearningAgentWorker(settings,AgentRunStore(base.engine))
    def stop(*_):worker.stopping=True
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    try:
        while not worker.stopping:
            try:
                worked=worker.callback_once();worked=worker.run_once() or worked
                if not worked:time.sleep(1)
            except Exception:log.exception("learning_agent_dependency_unavailable");time.sleep(5)
    finally:worker.close()


if __name__=="__main__":main()
