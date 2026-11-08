import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import or_, select, update, text
from dovideo.models import ProcessingJob, ResourceVersion

def enqueue(session, kind, idempotency_key, resource_version_id=None, payload=None):
    session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                    {'key': 'job:' + idempotency_key})
    existing = session.scalar(select(ProcessingJob).where(ProcessingJob.idempotency_key == idempotency_key))
    if existing:
        return existing
    job = ProcessingJob(id=uuid.uuid4(), kind=kind, idempotency_key=idempotency_key,
                        resource_version_id=resource_version_id, payload=payload or {}, state="QUEUED")
    session.add(job)
    session.flush()
    return job

def claim(session, worker_id: str, supported_kinds: tuple[str, ...], lease_seconds=60, target_id=None):
    now = datetime.now(timezone.utc)
    expired = (ProcessingJob.state == "RUNNING") & (ProcessingJob.lease_until < now)
    session.execute(update(ProcessingJob).where(expired, ProcessingJob.cancel_requested.is_(True))
                    .values(state="CANCELLED", lease_until=None, worker_id=None))
    session.execute(update(ProcessingJob).where(expired, ProcessingJob.attempts >= ProcessingJob.max_attempts)
                    .values(state="FAILED", error_code="LEASE_EXHAUSTED", lease_until=None, worker_id=None))
    for terminal in ('FAILED', 'CANCELLED'):
        parsed_versions = select(ProcessingJob.resource_version_id).where(
            ProcessingJob.kind == 'PROCESS_RESOURCE', ProcessingJob.state == terminal)
        session.execute(update(ResourceVersion).where(ResourceVersion.id.in_(parsed_versions),
                        ResourceVersion.state.in_(['PARSING','READY'])).values(state='PARSE_' + terminal))
        terminal_versions = select(ProcessingJob.resource_version_id).where(
            ProcessingJob.kind.in_(['VALIDATE_RESOURCE','IMPORT_RESOURCE']), ProcessingJob.state == terminal)
        session.execute(update(ResourceVersion).where(ResourceVersion.id.in_(terminal_versions),
                        ResourceVersion.state == 'VALIDATING').values(state=terminal))
    job = session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.kind.in_(supported_kinds), ProcessingJob.cancel_requested.is_(False),
            ProcessingJob.id == target_id if target_id else True,
            ProcessingJob.attempts < ProcessingJob.max_attempts,
            or_(
                (ProcessingJob.state == "QUEUED") & (ProcessingJob.available_at <= now),
                (ProcessingJob.state == "RUNNING") & (ProcessingJob.lease_until < now),
            )).order_by(ProcessingJob.created_at).with_for_update(skip_locked=True).limit(1))
    if job is None:
        return None
    job.state = "RUNNING"
    job.worker_id = worker_id
    job.lease_token = str(uuid.uuid4())
    job.lease_until = now + timedelta(seconds=lease_seconds)
    job.attempts += 1
    return job

def complete(session, job_id, lease_token):
    result = session.execute(update(ProcessingJob).where(
        ProcessingJob.id == job_id, ProcessingJob.lease_token == lease_token, ProcessingJob.state == "RUNNING",
        ProcessingJob.cancel_requested.is_(False), ProcessingJob.lease_until > datetime.now(timezone.utc))
        .values(state="SUCCEEDED", lease_until=None, updated_at=datetime.now(timezone.utc)))
    return result.rowcount == 1

def fail(session, job_id, lease_token, code, retry_delay=30, permanent=False):
    job = session.get(ProcessingJob, job_id, with_for_update=True)
    if job is None or job.lease_token != lease_token or job.state != "RUNNING":
        return False
    job.error_code = code[:80]
    job.lease_until = None
    job.worker_id = None
    if job.cancel_requested:
        job.state = "CANCELLED"
    elif permanent or job.attempts >= job.max_attempts:
        job.state = "FAILED"
    else:
        job.state = "QUEUED"
        job.available_at = datetime.now(timezone.utc) + timedelta(seconds=retry_delay)
    return True

def heartbeat(session, job_id, token, lease_seconds=60):
    now = datetime.now(timezone.utc)
    return session.execute(update(ProcessingJob).where(
        ProcessingJob.id == job_id, ProcessingJob.lease_token == token,
        ProcessingJob.state == 'RUNNING', ProcessingJob.cancel_requested.is_(False),
        ProcessingJob.lease_until > now).values(lease_until=now + timedelta(seconds=lease_seconds))).rowcount == 1
