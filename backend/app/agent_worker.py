"""Independent leased Agent process."""
import argparse
import time
import uuid
import os
import logging
import json
from threading import Event, Thread
from datetime import datetime,timedelta,timezone
from dovideo.config import Settings
from dovideo.storage import Storage
from dovideo.db import session_scope
from dovideo.models import AgentRun,AgentThread,AgentEvent,LearningPreference,LearningMemory
from sqlalchemy import select,update
from dovideo.agents.service import claim
from dovideo.agents.provider import ChatModel
from dovideo.agents.loop import make_loop
from dovideo.agents.context import history_view
from dovideo.agents.study import teaching_policy
from dovideo.agents.summary import prepare_history
from dovideo.agents.memory import save_explicit,select_memories
from dovideo.agents.checkpoints import restore,fingerprint
from dovideo.agents.reliability import AgentFailure,execution_scope

def run_once(storage,model=None):
    with session_scope(storage.engine) as session:
        row=claim(session)
        if row is None:return False
        run_id,token,model_id=row.id,row.lease_token,row.model_id
        thread=session.get(AgentThread,row.thread_id)
        context={'storage':storage,'user_id':thread.user_id,'course_id':thread.course_id,
                 'run_id':run_id,'lease_token':token,'teaching_policy':teaching_policy(row.input_text),
                 'retrieval_debug':os.getenv('DOVIDEO_RETRIEVAL_TRACE','0')=='1',
                 'stream':os.getenv('DOVIDEO_CHAT_STREAM','0')=='1'}
        try:
            # Durable deltas fence replay even if the graph checkpoint predates them.
            shown=session.scalars(select(AgentEvent).where(AgentEvent.run_id==run_id,
                AgentEvent.kind=='model.delta').order_by(AgentEvent.id)).all()
            if shown:
                row.answer=''.join(e.data.get('text','') for e in shown)
                raise AgentFailure('PARTIAL_STREAM')
            state=restore(row.checkpoint or {},fingerprint())
        except AgentFailure as exc:
            row.state='FAILED';row.error_code=exc.code;row.lease_until=None
            session.add(AgentEvent(run_id=run_id,kind='run.failed',data={'code':exc.code}))
            return True
        deadline=row.deadline_at
        context['request_id']=row.request_id
        recall_query=row.input_text
        if not state:
            history,task,recall_query=prepare_history(session,thread,row)
            state={'history':history,
                   'task_context':task,
                   'messages':[{'role':'user','content':row.input_text}],'phase':'model','calls':0}
            state.update(schema_version=1,config_fingerprint=fingerprint())
        actions=save_explicit(session,thread.user_id,thread.course_id,row.input_text,run_id)
        if actions:
            state['memory_actions']=actions
            context['teaching_policy']+=' 服务端已成功保存本次明确的学习声明或长期偏好，可简短告知用户；不要声称推测的掌握度已被证实。'
        context['memories'],memory_debug=select_memories(session,thread.user_id,thread.course_id,
            recall_query)
        if not memory_debug['enabled']:
            context['teaching_policy']+=' 用户已关闭学习记忆。本轮只能在当前会话使用其信息，不得声称已写入长期学习记忆。'
        if context['retrieval_debug']:state['memory_debug']=memory_debug
    def persist(state=None,kind=None,data=None):
        with session_scope(storage.engine) as session:
            row=session.get(AgentRun,run_id,with_for_update=True)
            if row.state!='RUNNING' or row.lease_token!=token or row.cancel_requested or row.lease_until<=datetime.now(timezone.utc):
                raise RuntimeError('RUN_CANCELLED_OR_LEASE_LOST')
            row.lease_until=datetime.now(timezone.utc)+timedelta(seconds=120)
            if state is not None:row.checkpoint=dict(state)
            if kind:session.add(AgentEvent(run_id=run_id,kind=kind,data=data or {}))
    stopped,lost=Event(),Event()
    saved_usage=state.get('usage',{})
    known_tokens=saved_usage.get('total_tokens',saved_usage.get('prompt_tokens',0)+saved_usage.get('completion_tokens',0))
    def renew():
        while not stopped.wait(20):
            try:
                now=datetime.now(timezone.utc)
                with session_scope(storage.engine) as session:
                    changed=session.execute(update(AgentRun).where(AgentRun.id==run_id,
                        AgentRun.state=='RUNNING',AgentRun.lease_token==token,
                        AgentRun.lease_until>now,AgentRun.cancel_requested.is_(False))
                        .values(lease_until=now+timedelta(seconds=120))).rowcount
                if not changed:
                    lost.set();return
            except Exception:
                lost.set();return
    def check():
        if lost.is_set():raise RuntimeError('RUN_CANCELLED_OR_LEASE_LOST')
        if deadline and datetime.now(timezone.utc)>=deadline:raise AgentFailure('RUN_DEADLINE_EXCEEDED')
        if known_tokens>=int(os.getenv('DOVIDEO_RUN_TOKEN_LIMIT','100000')):
            raise AgentFailure('RUN_TOKEN_LIMIT_EXCEEDED')
    ticker=Thread(target=renew,daemon=True)
    ticker.start()
    pending=[]
    last_emit=time.monotonic()
    def emit(kind,data):
        nonlocal last_emit
        if kind=='model.delta' and context['stream']:
            pending.append(data['text'])
            if time.monotonic()-last_emit<0.25:return
        if pending:
            persist(kind='model.delta',data={'text':''.join(pending)})
            pending.clear()
            last_emit=time.monotonic()
            if kind=='model.delta':return
        persist(kind=kind,data=data)
    try:
        model=model or ChatModel(model_id)
        def observe(kind,data):
            nonlocal known_tokens
            if kind=='model.completed':
                usage=data.get('usage',{})
                known_tokens+=usage.get('total_tokens',usage.get('prompt_tokens',0)+usage.get('completion_tokens',0))
            persist(kind='private.'+kind,data=data)
        seconds=max(0,(deadline-datetime.now(timezone.utc)).total_seconds()) if deadline else 300
        with execution_scope(run_id=str(run_id),request_id=context['request_id'],check=check,
                deadline=time.monotonic()+seconds,observe=observe):
            result=make_loop(model,context,lambda s:persist(state=s),emit,check).invoke(state)
        if pending:persist(kind='model.delta',data={'text':''.join(pending)})
        with session_scope(storage.engine) as session:
            row=session.get(AgentRun,run_id,with_for_update=True)
            if row.state!='RUNNING' or row.lease_token!=token or row.cancel_requested or row.lease_until<=datetime.now(timezone.utc):
                raise RuntimeError('RUN_CANCELLED_OR_LEASE_LOST')
            row.state='SUCCEEDED';row.answer=result.get('answer','');row.usage=result.get('usage',{})
            row.checkpoint=result;row.lease_until=None
            session.add(AgentEvent(run_id=run_id,kind='run.completed',data={'answer':row.answer}))
    except Exception as exc:
        # Preserve buffered partial text exactly once before the terminal event.
        if pending:
            try:persist(kind='model.delta',data={'text':''.join(pending)});pending.clear()
            except Exception:pass
        with session_scope(storage.engine) as session:
            row=session.get(AgentRun,run_id,with_for_update=True)
            if row.lease_token==token and row.state=='RUNNING' and row.lease_until>datetime.now(timezone.utc):
                row.state='CANCELLED' if row.cancel_requested else 'FAILED'
                row.error_code=getattr(exc,'code',type(exc).__name__)[:80];row.lease_until=None
                deltas=session.scalars(select(AgentEvent).where(AgentEvent.run_id==run_id,
                    AgentEvent.kind=='model.delta').order_by(AgentEvent.id)).all()
                if deltas:row.answer=''.join(e.data.get('text','') for e in deltas)
                elif row.error_code=='CITATION_VALIDATION_FAILED':
                    row.answer='本次回答的引用未通过校验，暂时无法提供可验证结论。请补充资料或缩小问题范围。'
                elif row.error_code=='EVIDENCE_SCOPE_UNSUPPORTED':
                    row.answer='本轮证据不足以核实资料全文是否包含所问内容，请补充页面或缩小范围。'
                session.add(AgentEvent(run_id=run_id,kind='run.cancelled' if row.cancel_requested else 'run.failed',data={'code':row.error_code}))
    finally:
        stopped.set()
        ticker.join(timeout=2)
    return True

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    storage=Storage(Settings.from_env())
    try:
        storage.ready()
        logging.basicConfig(level=logging.INFO,format='%(message)s')
        from dovideo.agents.observability import configure
        configure()
        last_health=0
        while True:
            try:
                worked=run_once(storage)
                if time.monotonic()-last_health>=60:
                    from dovideo.agents.observability import health
                    health(storage.engine);last_health=time.monotonic()
            except Exception as exc:
                logging.getLogger('dovideo.agent').error(json.dumps({'kind':'worker.cycle.failed','error_type':type(exc).__name__}))
                if args.once:raise
                time.sleep(1);continue
            if args.once:break
            if not worked:time.sleep(1)
    finally:storage.close()
if __name__=='__main__':main()
