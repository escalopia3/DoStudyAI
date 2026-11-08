"""Leased worker with isolated execution, heartbeats and bounded shutdown."""
import argparse
import logging
import multiprocessing
import queue
import signal
import socket
import time
import uuid
from sqlalchemy import select
from dovideo.config import Settings
from dovideo.storage import Storage
from dovideo.db import session_scope
from dovideo.business import jobs
from dovideo.models import ProcessingJob, Resource, ResourceVersion, UploadSession
from dovideo.handlers import SUPPORTED, execute

def run_once(storage, stop=lambda: False, timeout=3600, target_id=None):
    with session_scope(storage.engine) as session:
        job = jobs.claim(session, f'{socket.gethostname()}:{uuid.uuid4()}', SUPPORTED, target_id=target_id)
        if job is None:
            return False
        job_id, token = job.id, job.lease_token
        if job.kind == 'INDEX_RESOURCE':
            from dovideo.knowledge import prepare
            prepare(session, job, token)
        if job.kind == 'PROCESS_RESOURCE' and job.resource_version_id:
            session.get(ResourceVersion, job.resource_version_id).state = 'PARSING'
        snapshot = dict(job.payload, kind=job.kind, lease_token=token)
        if job.resource_version_id:
            version = session.get(ResourceVersion, job.resource_version_id)
            snapshot.update(version_id=str(version.id), key=version.object_key,
                            object_version_id=version.object_version_id, size=version.size_bytes,
                            content_type=version.content_type,expected_sha256=version.checksum_sha256)
    ctx = multiprocessing.get_context('spawn')
    output = ctx.Queue()
    process = ctx.Process(target=execute, args=(snapshot, output))
    result = None
    started = time.monotonic()
    heartbeat_at = started
    try:
        process.start()
        while result is None:
            if stop() or time.monotonic() - started > timeout:
                result = {'ok': False, 'code': 'WORKER_STOPPED' if stop() else 'TASK_TIMEOUT'}
                break
            try:
                result = output.get(timeout=0.5)
                break
            except queue.Empty:
                if not process.is_alive():
                    result = {'ok': False, 'code': 'EXECUTOR_EXITED'}
                    break
            if time.monotonic() - heartbeat_at >= 10:
                with session_scope(storage.engine) as session:
                    valid = jobs.heartbeat(session, job_id, token)
                if not valid:
                    result = {'ok': False, 'code': 'LEASE_LOST_OR_CANCELLED'}
                    break
                heartbeat_at = time.monotonic()
    finally:
        if process.pid:
            process.join(timeout=1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        output.close()
    with session_scope(storage.engine) as session:
        job = session.get(ProcessingJob, job_id, with_for_update=True)
        if result['ok'] and jobs.complete(session, job_id, token):
            if job.kind in ('VALIDATE_RESOURCE', 'IMPORT_RESOURCE'):
                version = session.get(ResourceVersion, job.resource_version_id)
                resource = session.get(Resource, version.resource_id, with_for_update=True)
                if resource.deleted_at is None:
                    version.object_key = result['key']
                    version.object_version_id = result['object_version_id']
                    version.checksum_sha256 = result['sha256']
                    version.state = 'READY'
                    jobs.enqueue(session, 'PROCESS_RESOURCE', f'process:{version.id}', version.id,
                                 {'resource_id': str(resource.id), 'course_id': job.payload['course_id']})
            elif job.kind == 'REFRESH_RESOURCE':
                from dovideo.business.reparse import publish_refresh
                publish_refresh(session,job,result['artifacts'])
            elif job.kind == 'PROCESS_RESOURCE':
                version = session.get(ResourceVersion, job.resource_version_id)
                resource = session.get(Resource, version.resource_id, with_for_update=True)
                if resource.deleted_at is None:
                    job.payload = dict(job.payload, artifacts=result['artifacts'])
                    version.state = 'PARSED'
                    session.flush()
                    from dovideo.knowledge import enqueue_index
                    enqueue_index(session, resource, version)
            elif job.kind == 'INDEX_RESOURCE':
                from dovideo.knowledge import publish
                publish(session, job, token, result)
            elif job.kind == 'DELETE_RESOURCE':
                session.get(ResourceVersion, job.resource_version_id).state = 'DELETED'
        else:
            changed = jobs.fail(session, job_id, token, result.get('code', 'LEASE_LOST'),
                      retry_delay=min(300, 2 ** job.attempts), permanent=result.get('permanent', False))
            if changed and job.resource_version_id and job.kind in ('VALIDATE_RESOURCE', 'IMPORT_RESOURCE') and job.state in ('FAILED', 'CANCELLED'):
                session.get(ResourceVersion, job.resource_version_id).state = job.state
            if changed and job.resource_version_id and job.kind == 'PROCESS_RESOURCE':
                session.get(ResourceVersion, job.resource_version_id).state = (
                    'PARSE_' + job.state if job.state in ('FAILED','CANCELLED') else 'READY')
            if changed and job.kind == 'INDEX_RESOURCE':
                from dovideo.models import KnowledgeIndex
                index = session.get(KnowledgeIndex, uuid.UUID(token))
                if index:
                    index.state = 'ABANDONED'
    return True

def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check', action='store_true')
    modes.add_argument('--once', action='store_true')
    modes.add_argument('--run', action='store_true')
    modes.add_argument('--maintenance', action='store_true')
    parser.add_argument('--timeout', type=int, default=3600)
    args = parser.parse_args()
    stopping = False
    def shutdown(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    storage = Storage(Settings.from_env())
    try:
        storage.ready()
        if args.check:
            print('Worker dependencies ready.')
            return
        if args.maintenance:
            from dovideo.maintenance import sweep
            sweep(storage)
            return
        maintenance_at = time.monotonic() + 300
        while not stopping:
            try:
                worked = run_once(storage, lambda: stopping, args.timeout)
                if args.run and time.monotonic() >= maintenance_at:
                    from dovideo.maintenance import sweep
                    sweep(storage)
                    maintenance_at = time.monotonic() + 300
            except Exception:
                logging.exception('Worker cycle failed; leased tasks remain recoverable')
                if args.once:
                    raise
                worked = False
            if args.once:
                break
            if not worked:
                time.sleep(1)
    finally:
        storage.close()

if __name__ == '__main__':
    main()
