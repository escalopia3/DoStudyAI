"""Durable SQL task queue. CAS fencing is required even after a lease expires."""
import hashlib
import json
import time
from sqlalchemy import (MetaData, Table, Column, String, Text, Integer, Float,
                        create_engine, select, update, or_, and_)
from sqlalchemy.exc import IntegrityError
from agent_service.contracts import ParseRequest

metadata = MetaData()
jobs = Table("ai_parse_jobs", metadata,
    Column("id", String(64), primary_key=True), Column("fingerprint", String(64), nullable=False),
    Column("payload", Text, nullable=False), Column("state", String(16), nullable=False),
    Column("attempt", Integer, nullable=False), Column("sequence", Integer, nullable=False),
    Column("lease_until", Float(precision=53), nullable=False), Column("available_at", Float(precision=53), nullable=False),
    Column("artifact_prefix", String(512)), Column("error_code", String(64)))
events = Table("ai_knowledge_outbox", metadata,
    Column("id", String(100), primary_key=True), Column("payload", Text, nullable=False),
    Column("delivered", Integer, nullable=False), Column("attempts", Integer, nullable=False),
    Column("available_at", Float(precision=53), nullable=False))


class Conflict(Exception): pass


class Store:
    def __init__(self, url):
        self.engine = create_engine(url, pool_pre_ping=True)

    def get(self, job_id):
        with self.engine.connect() as db:
            row = db.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
            return dict(row) if row else None

    def _event(self, db, row):
        request = json.loads(row["payload"])
        payload = dict(schemaVersion="1", jobId=row["id"], resourceId=request["resourceId"],
            sourceRevision=request["sourceRevision"], sequence=row["sequence"], state=row["state"],
            artifactPrefix=row.get("artifact_prefix"), errorCode=row.get("error_code"))
        db.execute(events.insert().values(id=f'{row["id"]}:{row["sequence"]}',
            payload=json.dumps(payload), delivered=0, attempts=0, available_at=0))

    def submit(self, request: ParseRequest):
        payload = json.dumps(request.model_dump(), sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        row = dict(id=request.jobId, fingerprint=fingerprint, payload=payload, state="QUEUED",
                   attempt=0, sequence=1, lease_until=0, available_at=0)
        try:
            with self.engine.begin() as db:
                db.execute(jobs.insert().values(**row))
                self._event(db, row)
        except IntegrityError:
            existing = self.get(request.jobId)
            if not existing or existing["fingerprint"] != fingerprint:
                raise Conflict("Idempotency key reused with different content")
        return self.get(request.jobId)

    def claim(self, lease_seconds=45, max_attempts=3):
        now = time.time()
        with self.engine.begin() as db:
            eligible = or_(and_(jobs.c.state == "QUEUED", jobs.c.available_at <= now),
                           and_(jobs.c.state == "RUNNING", jobs.c.lease_until < now))
            row = db.execute(select(jobs).where(eligible).order_by(jobs.c.available_at)
                             .limit(1).with_for_update(skip_locked=True)).mappings().first()
            if not row: return None
            row = dict(row)
            changes = dict(attempt=row["attempt"] + 1, sequence=row["sequence"] + 1,
                           state="RUNNING", lease_until=now + lease_seconds)
            if row["attempt"] >= max_attempts:
                changes.update(state="FAILED", error_code="ATTEMPTS_EXHAUSTED", lease_until=0)
            result = db.execute(update(jobs).where(jobs.c.id == row["id"],
                jobs.c.sequence == row["sequence"], eligible).values(**changes))
            if result.rowcount != 1: return None
            row.update(changes)
            self._event(db, row)
            return row if row["state"] == "RUNNING" else None

    def claim_index(self, lease_seconds=45, max_attempts=3):
        """Claim a parsed artifact for indexing, or recover an expired index lease."""
        now = time.time()
        with self.engine.begin() as db:
            eligible = or_(and_(jobs.c.state == "PARSED", jobs.c.available_at <= now),
                           and_(jobs.c.state == "INDEXING", jobs.c.lease_until < now))
            row = db.execute(select(jobs).where(eligible).order_by(jobs.c.available_at)
                             .limit(1).with_for_update(skip_locked=True)).mappings().first()
            if not row: return None
            row = dict(row)
            changes = dict(attempt=row["attempt"] + 1, sequence=row["sequence"] + 1,
                           state="INDEXING", lease_until=now + lease_seconds,
                           error_code=None)
            if row["attempt"] >= max_attempts:
                changes.update(state="FAILED", error_code="INDEX_ATTEMPTS_EXHAUSTED", lease_until=0)
            result = db.execute(update(jobs).where(jobs.c.id == row["id"],
                jobs.c.sequence == row["sequence"], eligible).values(**changes))
            if result.rowcount != 1: return None
            row.update(changes)
            self._event(db, row)
            return row if row["state"] == "INDEXING" else None

    def renew(self, job_id, attempt, seconds):
        now = time.time()
        with self.engine.begin() as db:
            return db.execute(update(jobs).where(jobs.c.id == job_id, jobs.c.attempt == attempt,
                jobs.c.state.in_(["RUNNING", "INDEXING"]), jobs.c.lease_until > now)
                .values(lease_until=now + seconds)).rowcount == 1

    def finish(self, job_id, attempt, state, artifact=None, error=None, retry=False):
        with self.engine.begin() as db:
            row = db.execute(select(jobs).where(jobs.c.id == job_id).with_for_update()).mappings().first()
            now = time.time()
            if not row or row["attempt"] != attempt or row["state"] not in ("RUNNING", "INDEXING") or row["lease_until"] <= now:
                return False
            row = dict(row)
            retry_state = "PARSED" if row["state"] == "INDEXING" else "QUEUED"
            changes = dict(state=retry_state if retry else state,
                artifact_prefix=artifact if artifact is not None else row.get("artifact_prefix"),
                error_code=error, sequence=row["sequence"]+1, lease_until=0,
                available_at=now + min(300, 2 ** attempt))
            result = db.execute(update(jobs).where(jobs.c.id == job_id,
                jobs.c.sequence == row["sequence"], jobs.c.state == row["state"]).values(**changes))
            if result.rowcount != 1: return False
            row.update(changes)
            self._event(db, row)
            return True

    def cancel(self, job_id):
        with self.engine.begin() as db:
            row = db.execute(select(jobs).where(jobs.c.id == job_id).with_for_update()).mappings().first()
            if not row: return None
            row = dict(row)
            if row["state"] in ("READY", "FAILED", "CANCELLED"): return row
            changes = dict(state="CANCELLED", sequence=row["sequence"]+1, lease_until=0)
            result = db.execute(update(jobs).where(jobs.c.id == job_id,
                jobs.c.sequence == row["sequence"]).values(**changes))
            if result.rowcount != 1: raise Conflict("Concurrent job update; retry cancellation")
            row.update(changes)
            self._event(db, row)
            return row
