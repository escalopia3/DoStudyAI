"""Enqueue existing PARSED resources; no parsing or embedding in this process."""
from sqlalchemy import select
from dovideo.config import Settings
from dovideo.db import session_scope
from dovideo.storage import Storage
from dovideo.models import Resource, ResourceVersion, ActiveKnowledgeIndex
from dovideo.knowledge import enqueue_index

def main():
    storage = Storage(Settings.from_env())
    count = 0
    try:
        with session_scope(storage.engine) as session:
            rows = session.execute(select(Resource,ResourceVersion).join(ResourceVersion,
                ResourceVersion.id == Resource.current_version_id).outerjoin(ActiveKnowledgeIndex,
                ActiveKnowledgeIndex.resource_id == Resource.id).where(Resource.deleted_at.is_(None),
                ResourceVersion.state == 'PARSED',ActiveKnowledgeIndex.resource_id.is_(None))
                .with_for_update(of=Resource,skip_locked=True)).all()
            for resource,version in rows:
                job = enqueue_index(session,resource,version)
                count += job.state == 'QUEUED'
        print(f'Queued existing parsed resources: {count}')
    finally:
        storage.close()

if __name__ == '__main__':
    main()
