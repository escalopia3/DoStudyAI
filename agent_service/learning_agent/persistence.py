from __future__ import annotations

import hashlib
import json
import time
from sqlalchemy import Column, Float, Integer, String, Table, Text, and_, or_, select, update
from sqlalchemy.exc import IntegrityError

from agent_service.store import metadata
from agent_service.learning_agent.schemas import AgentRunRequest, AgentRunResult


agent_runs = Table("ai_agent_runs", metadata,
    Column("run_id", String(64), primary_key=True), Column("fingerprint", String(64), nullable=False),
    Column("payload_json", Text, nullable=False), Column("state", String(24), nullable=False),
    Column("attempt", Integer, nullable=False), Column("sequence", Integer, nullable=False),
    Column("lease_until", Float, nullable=False), Column("available_at", Float, nullable=False),
    Column("deadline_at", Float, nullable=False), Column("checkpoint_json", Text),
    Column("result_json", Text), Column("error_code", String(64)),
    Column("created_at", Float, nullable=False), Column("updated_at", Float, nullable=False))

agent_events = Table("ai_agent_outbox", metadata,
    Column("event_id", String(100), primary_key=True), Column("run_id", String(64), nullable=False),
    Column("sequence", Integer, nullable=False), Column("payload_json", Text, nullable=False),
    Column("delivered", Integer, nullable=False), Column("attempts", Integer, nullable=False),
    Column("available_at", Float, nullable=False))


class AgentRunConflict(Exception): pass


class AgentRunStore:
    def __init__(self, engine): self.engine = engine

    def _event(self, db, row):
        payload = {"schemaVersion": "1", "runId": row["run_id"], "state": row["state"],
                   "sequence": row["sequence"], "errorCode": row.get("error_code")}
        if row.get("result_json"):
            payload["result"] = json.loads(row["result_json"])
        db.execute(agent_events.insert().values(event_id=f'{row["run_id"]}:{row["sequence"]}',
            run_id=row["run_id"], sequence=row["sequence"], payload_json=json.dumps(payload),
            delivered=0, attempts=0, available_at=0))

    def submit(self, request: AgentRunRequest):
        payload = request.model_dump_json()
        fingerprint = hashlib.sha256(payload.encode()).hexdigest(); now = time.time()
        row = dict(run_id=request.runId, fingerprint=fingerprint, payload_json=payload,
            state="QUEUED", attempt=0, sequence=1, lease_until=0, available_at=0,
            deadline_at=request.deadlineAt, checkpoint_json=None, result_json=None,
            error_code=None, created_at=now, updated_at=now)
        try:
            with self.engine.begin() as db:
                db.execute(agent_runs.insert().values(**row)); self._event(db, row)
        except IntegrityError:
            existing = self.get(request.runId)
            if not existing or existing["fingerprint"] != fingerprint:
                raise AgentRunConflict("Run id reused with different request")
        return self.get(request.runId)

    def get(self, run_id: str):
        with self.engine.connect() as db:
            row = db.execute(select(agent_runs).where(agent_runs.c.run_id == run_id)).mappings().first()
            return dict(row) if row else None

    def claim(self, lease_seconds: int = 45, max_attempts: int = 2):
        now = time.time()
        with self.engine.begin() as db:
            eligible = or_(and_(agent_runs.c.state == "QUEUED", agent_runs.c.available_at <= now),
                           and_(agent_runs.c.state == "RUNNING", agent_runs.c.lease_until < now))
            row = db.execute(select(agent_runs).where(eligible, agent_runs.c.deadline_at > now)
                .order_by(agent_runs.c.available_at).limit(1).with_for_update(skip_locked=True)).mappings().first()
            if not row: return None
            row = dict(row); attempt = row["attempt"] + 1
            changes = dict(state="RUNNING", attempt=attempt, sequence=row["sequence"]+1,
                           lease_until=now+lease_seconds, updated_at=now)
            if attempt > max_attempts: changes.update(state="FAILED",error_code="ATTEMPTS_EXHAUSTED",lease_until=0)
            db.execute(update(agent_runs).where(agent_runs.c.run_id==row["run_id"],
                agent_runs.c.sequence==row["sequence"],eligible).values(**changes))
            row.update(changes); self._event(db,row)
            return row if row["state"]=="RUNNING" else None

    def renew(self, run_id: str, attempt: int, seconds: int) -> bool:
        now=time.time()
        with self.engine.begin() as db:
            return db.execute(update(agent_runs).where(agent_runs.c.run_id==run_id,
                agent_runs.c.attempt==attempt,agent_runs.c.state=="RUNNING",
                agent_runs.c.lease_until>now).values(lease_until=now+seconds,updated_at=now)).rowcount==1

    def checkpoint(self, run_id: str, attempt: int, node: str, state: dict) -> bool:
        now=time.time(); value=json.dumps({"node":node,"state":state},ensure_ascii=False)
        with self.engine.begin() as db:
            return db.execute(update(agent_runs).where(agent_runs.c.run_id==run_id,
                agent_runs.c.attempt==attempt,agent_runs.c.state=="RUNNING",
                agent_runs.c.lease_until>now).values(checkpoint_json=value,updated_at=now)).rowcount==1

    def finish(self, run_id: str, attempt: int, result: AgentRunResult | None,
               state: str, error: str | None = None) -> bool:
        now=time.time()
        with self.engine.begin() as db:
            row=db.execute(select(agent_runs).where(agent_runs.c.run_id==run_id).with_for_update()).mappings().first()
            if not row or row["attempt"]!=attempt or row["state"]!="RUNNING" or row["lease_until"]<=now:return False
            changes=dict(state=state,sequence=row["sequence"]+1,lease_until=0,updated_at=now,
                result_json=result.model_dump_json() if result else None,error_code=error)
            db.execute(update(agent_runs).where(agent_runs.c.run_id==run_id,
                agent_runs.c.sequence==row["sequence"]).values(**changes))
            saved=dict(row);saved.update(changes);self._event(db,saved);return True

    def cancel(self, run_id: str):
        now=time.time()
        with self.engine.begin() as db:
            row=db.execute(select(agent_runs).where(agent_runs.c.run_id==run_id).with_for_update()).mappings().first()
            if not row:return None
            row=dict(row)
            if row["state"] in ("COMPLETED","FAILED","CANCELLED","TIMED_OUT","BUDGET_EXCEEDED"):return row
            changes=dict(state="CANCELLED",sequence=row["sequence"]+1,lease_until=0,updated_at=now)
            db.execute(update(agent_runs).where(agent_runs.c.run_id==run_id,
                agent_runs.c.sequence==row["sequence"]).values(**changes))
            row.update(changes);self._event(db,row);return row
