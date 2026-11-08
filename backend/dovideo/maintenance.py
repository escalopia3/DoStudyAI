"""Explicitly scoped maintenance; preserves formal objects and live uploads."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, select
from dovideo.db import session_scope
from dovideo.models import AuthSession, LoginAttempt, UploadSession, ResourceVersion, ProcessingJob

def sweep(storage):
    now = datetime.now(timezone.utc)
    with session_scope(storage.engine) as session:
        from dovideo.models import KnowledgeIndex, ActiveKnowledgeIndex, Resource
        from dovideo.knowledge import scope_filter
        candidates = session.scalars(select(KnowledgeIndex).where(
            KnowledgeIndex.created_at < now - timedelta(days=1),
            KnowledgeIndex.state != 'CLEANED').limit(100)).all()
        for index in candidates:
            # Publication and deletion take the same resource lock.
            session.get(Resource,index.resource_id,with_for_update=True)
            active = session.get(ActiveKnowledgeIndex,index.resource_id)
            job = session.get(ProcessingJob,index.job_id)
            if (active and active.index_id == index.id) or (job and job.state in ('RUNNING','QUEUED')):
                continue
            if storage.qdrant.collection_exists(index.collection):
                storage.qdrant.delete(index.collection,
                    points_selector=scope_filter(index_id=index.id,resource_id=index.resource_id),wait=True)
            for obj in storage.minio.list_objects(storage.bucket,
                    prefix=f'indexes/{index.resource_version_id}/{index.id}/',include_version=True,recursive=True):
                storage.minio.remove_object(storage.bucket,obj.object_name,version_id=obj.version_id)
            index.state = 'CLEANED'
        session.execute(delete(AuthSession).where(AuthSession.expires_at < now))
        session.execute(delete(LoginAttempt).where(LoginAttempt.window_started_at < now - timedelta(days=1)))
        published = set()
        from dovideo.business.reparse import retained_artifact_keys
        for job in session.scalars(select(ProcessingJob).where(ProcessingJob.kind.in_(['PROCESS_RESOURCE','REFRESH_RESOURCE']), ProcessingJob.state == 'SUCCEEDED')):
            published.update(retained_artifact_keys(job.payload))
        for obj in storage.minio.list_objects(storage.bucket, prefix='artifacts/', include_version=True, recursive=True):
            if obj.object_name in published or obj.last_modified is None or obj.last_modified > now - timedelta(days=1):
                continue
            import uuid
            try:
                version_id = uuid.UUID(obj.object_name.split('/')[1])
            except (ValueError, IndexError):
                continue
            active = session.scalar(select(ProcessingJob.id).where(ProcessingJob.resource_version_id == version_id,
                ProcessingJob.kind.in_(['PROCESS_RESOURCE','REFRESH_RESOURCE']), ProcessingJob.state.in_(['QUEUED','RUNNING'])))
            if not active:
                storage.minio.remove_object(storage.bucket, obj.object_name, version_id=obj.version_id)
        uploads = session.scalars(select(UploadSession).where(UploadSession.expires_at < now - timedelta(hours=1)).limit(100)).all()
        for upload in uploads:
            if upload.resource_id:
                version = session.scalar(select(ResourceVersion).where(ResourceVersion.resource_id == upload.resource_id))
                # Failed validation remains retryable; retain its source.
                if version is None or version.state not in ('READY', 'PARSED', 'INDEXED', 'DELETED'):
                    continue
            for obj in storage.minio.list_objects(storage.bucket, prefix=upload.object_key, include_version=True, recursive=True):
                if obj.object_name == upload.object_key or obj.object_name.startswith(upload.object_key + '.parts/'):
                    storage.minio.remove_object(storage.bucket, obj.object_name, version_id=obj.version_id)
            if upload.state == 'PENDING':
                upload.state = 'EXPIRED'
        # Remove abandoned attempt objects only after a grace period and no active validator.
        for obj in storage.minio.list_objects(storage.bucket, prefix='resources/', include_version=True, recursive=True):
            if obj.last_modified is None or obj.last_modified > now - timedelta(days=1):
                continue
            linked = session.scalar(select(ResourceVersion.id).where(ResourceVersion.object_key == obj.object_name))
            if linked:
                continue
            import uuid
            try:
                version_id = uuid.UUID(obj.object_name.split('/')[1])
            except (ValueError, IndexError):
                continue
            active = session.scalar(select(ProcessingJob.id).where(ProcessingJob.resource_version_id == version_id,
                ProcessingJob.state.in_(['QUEUED','RUNNING']), ProcessingJob.kind.in_(['VALIDATE_RESOURCE','IMPORT_RESOURCE'])))
            if not active:
                storage.minio.remove_object(storage.bucket, obj.object_name, version_id=obj.version_id)
