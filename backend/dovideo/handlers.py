import hashlib
import tempfile
from dovideo.config import Settings
from dovideo.storage import Storage
from dovideo.validation import check_format, InvalidResource

SUPPORTED = ('SYSTEM_NOOP', 'VALIDATE_RESOURCE', 'IMPORT_RESOURCE', 'DELETE_RESOURCE', 'PROCESS_RESOURCE', 'REFRESH_RESOURCE', 'INDEX_RESOURCE')

def execute(snapshot, output):
    """Runs in a disposable subprocess; only the parent may publish DB state."""
    storage = None
    try:
        if snapshot['kind'] == 'SYSTEM_NOOP':
            output.put({'ok': True})
            return
        storage = Storage(Settings.from_env())
        if snapshot['kind'] == 'INDEX_RESOURCE':
            from dovideo.knowledge import build
            output.put(build(storage, snapshot))
            return
        if snapshot['kind'] in ('PROCESS_RESOURCE','REFRESH_RESOURCE'):
            from dovideo.parsing import process
            output.put(process(storage, snapshot))
            return
        if snapshot['kind'] == 'DELETE_RESOURCE':
            from sqlalchemy import select
            from sqlalchemy.orm import Session
            from dovideo.models import ResourceVersion, KnowledgeIndex
            from dovideo.knowledge import scope_filter
            with Session(storage.engine) as session:
                version = session.get(ResourceVersion, snapshot['version_id'])
                for collection in session.scalars(select(KnowledgeIndex.collection).where(
                        KnowledgeIndex.resource_id == version.resource_id).distinct()):
                    if storage.qdrant.collection_exists(collection):
                        storage.qdrant.delete(collection, points_selector=scope_filter(resource_id=version.resource_id), wait=True)
            for obj in storage.minio.list_objects(storage.bucket, prefix=f"indexes/{snapshot['version_id']}/", include_version=True, recursive=True):
                storage.minio.remove_object(storage.bucket, obj.object_name, version_id=obj.version_id)
            if snapshot.get('version_id'):
                prefix = f"artifacts/{snapshot['version_id']}/"
                for obj in storage.minio.list_objects(storage.bucket, prefix=prefix, include_version=True, recursive=True):
                    storage.minio.remove_object(storage.bucket, obj.object_name, version_id=obj.version_id)
            # Delete all object versions, including superseded uploads and attempts.
            for key in snapshot['keys']:
                for obj in storage.minio.list_objects(storage.bucket, prefix=key, include_version=True, recursive=True):
                    if obj.object_name == key or obj.object_name.startswith(key + '.parts/'):
                        storage.minio.remove_object(storage.bucket, obj.object_name, version_id=obj.version_id)
            output.put({'ok': True})
            return
        connection = None
        if snapshot['kind'] == 'IMPORT_RESOURCE':
            from dovideo.urlfetch import open_source
            connection, response = open_source(snapshot['url'])
            chunks = iter(lambda: response.read(1024 * 1024), b'')
        else:
            response = storage.minio.get_object(storage.bucket, snapshot['key'], version_id=snapshot['object_version_id'])
            chunks = response.stream(1024 * 1024)
        try:
            with tempfile.TemporaryFile() as stream:
                digest = hashlib.sha256()
                size = 0
                for chunk in chunks:
                    size += len(chunk)
                    if size > snapshot['size']:
                        raise InvalidResource('SIZE_MISMATCH')
                    digest.update(chunk)
                    stream.write(chunk)
                if size != snapshot['size']:
                    raise InvalidResource('SIZE_MISMATCH')
                checksum = digest.hexdigest()
                if snapshot.get('expected_sha256') and checksum != snapshot['expected_sha256']:
                    raise InvalidResource('CHECKSUM_MISMATCH')
                check_format(stream, snapshot['content_type'])
                # Each attempt owns a separate object; stale attempts cannot overwrite a winner.
                key = f"resources/{snapshot['version_id']}/{snapshot['lease_token']}"
                result = storage.minio.put_object(storage.bucket, key, stream, size, content_type=snapshot['content_type'])
                output.put({'ok': True, 'key': key, 'object_version_id': result.version_id, 'sha256': checksum})
        finally:
            response.close()
            if connection:
                connection.close()
            else:
                response.release_conn()
    except InvalidResource as exc:
        output.put({'ok': False, 'code': str(exc), 'permanent': True})
    except Exception as exc:
        output.put({'ok': False, 'code': type(exc).__name__, 'permanent': False})
    finally:
        if storage:
            storage.close()
