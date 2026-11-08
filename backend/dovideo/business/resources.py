import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from sqlalchemy import select
from dovideo.business.courses import require_owned_course
from dovideo.business.jobs import enqueue
from dovideo.errors import ApiError
from dovideo.models import Course, User, CourseChapter, CourseResource, ProcessingJob, Resource, ResourceVersion, UploadSession

IDEMPOTENCY = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
PART_SIZE = 16 * 1024 * 1024
ALLOWED = {
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PPTX",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
    "video/mp4": "VIDEO", "video/webm": "VIDEO", "audio/mpeg": "AUDIO",
    "audio/wav": "AUDIO", "image/png": "IMAGE", "image/jpeg": "IMAGE",
}

def _filename(value):
    name = PurePath(value.replace("\\", "/")).name.strip()
    if not name or name in {".", ".."} or any(ord(c) < 32 for c in name):
        raise ApiError(400, "INVALID_FILENAME", "文件名无效")
    return name

def initiate(session, storage, settings, user, course_id, key, data):
    require_owned_course(session, course_id, user.id)
    session.get(User, user.id, with_for_update=True)
    if not IDEMPOTENCY.fullmatch(key or ""):
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key格式无效")
    if data.chapter_id:
        chapter = session.get(CourseChapter, data.chapter_id)
        if chapter is None or chapter.course_id != course_id:
            raise ApiError(400, "INVALID_CHAPTER", "章节不属于当前课程")
    filename = _filename(data.filename)
    kind = ALLOWED.get(data.content_type)
    if kind is None:
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "暂不支持此文件类型")
    fingerprint = hashlib.sha256(f"{course_id}\n{data.chapter_id}\n{filename}\n{data.content_type}\n{data.size_bytes}\n{data.sha256}".encode()).hexdigest()
    existing = session.scalar(select(UploadSession).where(
        UploadSession.user_id == user.id, UploadSession.idempotency_key == key))
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "上传标识已用于不同文件或归档位置")
        if existing.state != "COMPLETED" and existing.expires_at < datetime.now(timezone.utc):
            raise ApiError(410, "UPLOAD_EXPIRED", "上传任务已过期，请使用新的上传标识")
        return upload_view(storage, settings, existing)
    suffix = PurePath(filename).suffix.lower()[:12]
    upload = UploadSession(id=uuid.uuid4(), user_id=user.id, course_id=course_id,
        chapter_id=data.chapter_id, idempotency_key=key, request_fingerprint=fingerprint,
        filename=filename, content_type=data.content_type, expected_size=data.size_bytes, expected_sha256=data.sha256,
        object_key=f"uploads/{user.id}/{uuid.uuid4()}{suffix}", state="PENDING",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.upload_expiry_minutes))
    session.add(upload)
    session.flush()
    return upload_view(storage, settings, upload)

def upload_view(storage, settings, upload):
    result = {"uploadId": str(upload.id), "state": upload.state, "expiresAt": upload.expires_at.isoformat()}
    if upload.state == "COMPLETED":
        result["resourceId"] = str(upload.resource_id)
    elif upload.state != 'PENDING':
        return result
    else:
        if upload.expected_size > PART_SIZE:
            result.update(mode='parts', partSize=PART_SIZE,
                          partCount=(upload.expected_size + PART_SIZE - 1) // PART_SIZE)
            return result
        result["method"] = "PUT"
        result["uploadUrl"] = storage.minio.presigned_put_object(
            storage.bucket, upload.object_key, expires=timedelta(seconds=max(1, int((upload.expires_at - datetime.now(timezone.utc)).total_seconds()))))
        result["headers"] = {"Content-Type": upload.content_type}
    return result

def complete_upload(session, storage, user, upload_id):
    upload = session.get(UploadSession, upload_id, with_for_update=True)
    if upload is None or upload.user_id != user.id:
        raise ApiError(404, "UPLOAD_NOT_FOUND", "上传任务不存在")
    require_owned_course(session, upload.course_id, user.id)
    if upload.state == "COMPLETED":
        version = session.scalar(select(ResourceVersion).where(ResourceVersion.resource_id == upload.resource_id))
        job = session.scalar(select(ProcessingJob).where(ProcessingJob.idempotency_key == f'validate:{version.id}'))
        return {"resourceId": str(upload.resource_id), "versionId": str(version.id), "jobId": str(job.id), "state": job.state}
    if upload.state != 'PENDING':
        raise ApiError(409, 'UPLOAD_CLOSED', '上传已关闭')
    if upload.expires_at < datetime.now(timezone.utc):
        raise ApiError(410, "UPLOAD_EXPIRED", "上传任务已过期")
    if upload.expected_size > PART_SIZE:
        from minio.commonconfig import ComposeSource
        sources = []
        for number in range(1, (upload.expected_size + PART_SIZE - 1) // PART_SIZE + 1):
            key = f'{upload.object_key}.parts/{number}'
            try:
                part = storage.minio.stat_object(storage.bucket, key)
            except Exception:
                raise ApiError(409, 'PART_MISSING', f'分片{number}尚未上传')
            if part.size != min(PART_SIZE, upload.expected_size - (number - 1) * PART_SIZE):
                raise ApiError(409, 'PART_SIZE_MISMATCH', f'分片{number}大小不匹配')
            sources.append(ComposeSource(storage.bucket, key, version_id=part.version_id))
        storage.minio.compose_object(storage.bucket, upload.object_key, sources,
                                     metadata={'Content-Type': upload.content_type})
    try:
        stat = storage.minio.stat_object(storage.bucket, upload.object_key)
    except Exception:
        raise ApiError(409, "UPLOAD_INCOMPLETE", "对象尚未上传完成")
    if stat.size != upload.expected_size:
        raise ApiError(409, "UPLOAD_SIZE_MISMATCH", "上传文件大小与登记信息不一致")
    if upload.expected_size <= PART_SIZE and stat.content_type and stat.content_type != upload.content_type:
        raise ApiError(409, "UPLOAD_TYPE_MISMATCH", "上传文件类型与登记信息不一致")
    if not stat.version_id or stat.version_id == 'null':
        raise ApiError(503, 'VERSIONING_REQUIRED', '对象版本控制尚未启用，请重新上传')
    upload.object_version_id = stat.version_id
    resource = Resource(id=uuid.uuid4(), owner_id=user.id, kind=ALLOWED[upload.content_type],
                        display_name=upload.filename, current_version_id=None)
    session.add(resource)
    session.flush()
    version = ResourceVersion(id=uuid.uuid4(), resource_id=resource.id, version_no=1,
        object_key=upload.object_key, object_version_id=stat.version_id,
        content_type=upload.content_type, size_bytes=stat.size, state="VALIDATING")
    session.add(version)
    session.flush()
    resource.current_version_id = version.id
    session.add(CourseResource(course_id=upload.course_id, resource_id=resource.id,
                    chapter_id=upload.chapter_id, added_by=user.id))
    session.flush()
    job = enqueue(session, "VALIDATE_RESOURCE", f"validate:{version.id}", version.id,
                  {"course_id": str(upload.course_id), "resource_id": str(resource.id),
                   "expected_sha256": upload.expected_sha256})
    upload.state = "COMPLETED"
    upload.resource_id = resource.id
    return {"resourceId": str(resource.id), "versionId": str(version.id), "jobId": str(job.id), "state": job.state}

def list_resources(session, user, course_id):
    require_owned_course(session, course_id, user.id)
    rows = session.execute(select(Resource, ResourceVersion, CourseResource).join(
        CourseResource, CourseResource.resource_id == Resource.id).join(
        ResourceVersion, ResourceVersion.id == Resource.current_version_id).where(
        CourseResource.course_id == course_id, Resource.deleted_at.is_(None)).order_by(Resource.created_at.desc())).all()
    return [{"id": str(r.id), "filename": r.display_name, "kind": r.kind,
             "versionId": str(v.id), "state": v.state, "sizeBytes": v.size_bytes,
             "chapterId": str(link.chapter_id) if link.chapter_id else None} for r, v, link in rows]

def download(session, storage, user, resource_id):
    row = session.execute(select(Resource, ResourceVersion, CourseResource).join(
        ResourceVersion, ResourceVersion.id == Resource.current_version_id).join(
        CourseResource, CourseResource.resource_id == Resource.id).join(
        Course, Course.id == CourseResource.course_id).where(
        Resource.id == resource_id, Resource.deleted_at.is_(None), Course.created_by == user.id)).first()
    if row is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "资料不存在")
    resource, version, link = row
    if version.state not in {'READY', 'PARSING', 'PARSED', 'PARSE_FAILED', 'PARSE_CANCELLED', 'INDEXED'}:
        raise ApiError(409, 'RESOURCE_NOT_READY', '资料尚未通过校验')
    return {"url": storage.minio.presigned_get_object(storage.bucket, version.object_key,
            version_id=version.object_version_id, expires=timedelta(minutes=10))}

def job_status(session, user, job_id):
    row = session.execute(select(ProcessingJob, ResourceVersion, CourseResource).join(
        ResourceVersion, ResourceVersion.id == ProcessingJob.resource_version_id).join(
        CourseResource, CourseResource.resource_id == ResourceVersion.resource_id).join(
        Course, Course.id == CourseResource.course_id).where(
        ProcessingJob.id == job_id, Course.created_by == user.id)).first()
    if row is None:
        raise ApiError(404, "JOB_NOT_FOUND", "任务不存在")
    job, version, link = row
    return {"id": str(job.id), "kind": job.kind, "state": job.state, "attempts": job.attempts,
            "errorCode": job.error_code, "resourceVersionId": str(version.id)}

def cancel_job(session, user, job_id):
    job_status(session, user, job_id)
    job = session.get(ProcessingJob, job_id, with_for_update=True)
    if job.state in ('SUCCEEDED','FAILED','CANCELLED'):
        return {'id': str(job.id), 'state': job.state, 'cancelRequested': job.cancel_requested}
    job.cancel_requested = True
    if job.state == "QUEUED":
        job.state = "CANCELLED"
        if job.kind in ('VALIDATE_RESOURCE','IMPORT_RESOURCE'):
            session.get(ResourceVersion, job.resource_version_id).state = 'CANCELLED'
        elif job.kind == 'PROCESS_RESOURCE':
            session.get(ResourceVersion, job.resource_version_id).state = 'PARSE_CANCELLED'
    return {"id": str(job.id), "state": job.state, "cancelRequested": True}

def upload_parts(session, storage, user, upload_id, number=None):
    upload = session.get(UploadSession, upload_id)
    if upload is None or upload.user_id != user.id:
        raise ApiError(404, 'UPLOAD_NOT_FOUND', '上传不存在')
    require_owned_course(session, upload.course_id, user.id)
    if upload.state != 'PENDING' or upload.expires_at <= datetime.now(timezone.utc):
        raise ApiError(410, 'UPLOAD_CLOSED', '上传已关闭或过期')
    count = (upload.expected_size + PART_SIZE - 1) // PART_SIZE
    if number is not None:
        if upload.expected_size <= PART_SIZE or not 1 <= number <= count:
            raise ApiError(400, 'INVALID_PART', '分片编号无效')
        remaining = max(1, int((upload.expires_at - datetime.now(timezone.utc)).total_seconds()))
        return {'uploadUrl': storage.minio.presigned_put_object(storage.bucket,
                f'{upload.object_key}.parts/{number}', expires=timedelta(seconds=remaining)), 'method': 'PUT'}
    return {'parts': [{'number': int(obj.object_name.rsplit('/', 1)[1]), 'size': obj.size}
                      for obj in storage.minio.list_objects(storage.bucket, prefix=upload.object_key + '.parts/', recursive=True)]}

def retry_job(session, user, job_id):
    job_status(session, user, job_id)
    job = session.get(ProcessingJob, job_id, with_for_update=True)
    version = session.get(ResourceVersion, job.resource_version_id)
    resource = session.get(Resource, version.resource_id)
    if resource.deleted_at or job.state not in ('FAILED', 'CANCELLED'):
        raise ApiError(409, 'RETRY_NOT_ALLOWED', '任务当前不能重试')
    job.state, job.attempts, job.cancel_requested = 'QUEUED', 0, False
    job.lease_token = job.worker_id = job.lease_until = job.error_code = None
    job.available_at = datetime.now(timezone.utc)
    if job.kind in ('VALIDATE_RESOURCE','IMPORT_RESOURCE'):
        version.state = 'VALIDATING'
    elif job.kind == 'PROCESS_RESOURCE':
        version.state = 'READY'
    elif job.kind == 'INDEX_RESOURCE' and job.payload.get('config',{}).get('configurationError'):
        from dovideo.knowledge import index_config, collection_name
        try:
            config = index_config()
        except ValueError:
            raise ApiError(409,'INDEX_CONFIGURATION_MISSING','请先完成Embedding配置再重试')
        job.payload = dict(job.payload, config=config, collection=collection_name(config))
    return {'id': str(job.id), 'state': job.state}

def delete_resource(session, user, resource_id):
    resource = session.get(Resource, resource_id, with_for_update=True)
    if resource is None or resource.owner_id != user.id:
        raise ApiError(404, 'RESOURCE_NOT_FOUND', '资料不存在')
    if resource.deleted_at:
        return {'id': str(resource_id), 'state': 'DELETED'}
    resource.deleted_at = datetime.now(timezone.utc)
    versions = session.scalars(select(ResourceVersion).where(ResourceVersion.resource_id == resource_id)).all()
    for version in versions:
        active = session.scalars(select(ProcessingJob).where(ProcessingJob.resource_version_id == version.id,
                                  ProcessingJob.state.in_(['QUEUED','RUNNING']))).all()
        for job in active:
            job.cancel_requested = True
            if job.state == 'QUEUED':
                job.state = 'CANCELLED'
        upload = session.scalar(select(UploadSession).where(UploadSession.resource_id == resource_id))
        keys = [version.object_key]
        if upload:
            keys.append(upload.object_key)
        cleanup = enqueue(session, 'DELETE_RESOURCE', f'delete:{version.id}', version.id, {'keys': keys})
        cleanup.available_at = datetime.now(timezone.utc) + timedelta(minutes=31)
    return {'id': str(resource_id), 'state': 'DELETED'}

def cancel_upload(session, user, upload_id):
    upload = session.get(UploadSession, upload_id, with_for_update=True)
    if upload is None or upload.user_id != user.id:
        raise ApiError(404, 'UPLOAD_NOT_FOUND', '上传不存在')
    require_owned_course(session, upload.course_id, user.id)
    if upload.state == 'COMPLETED':
        raise ApiError(409, 'UPLOAD_COMPLETED', '已完成上传请使用资料删除接口')
    upload.state = 'CANCELLED'
    return {'uploadId': str(upload.id), 'state': upload.state}

def import_url(session, user, course_id, key, data):
    from dovideo.urlfetch import validate_url
    from dovideo.validation import InvalidResource
    try:
        validate_url(data.url)
    except (InvalidResource, ValueError):
        raise ApiError(400, 'URL_NOT_ALLOWED', '仅支持配置白名单中的HTTPS直链')
    require_owned_course(session, course_id, user.id)
    session.get(User, user.id, with_for_update=True)
    if not IDEMPOTENCY.fullmatch(key or '') or data.content_type not in ALLOWED:
        raise ApiError(400, 'INVALID_IMPORT', '导入参数无效')
    if data.chapter_id:
        chapter = session.get(CourseChapter, data.chapter_id)
        if not chapter or chapter.course_id != course_id:
            raise ApiError(400, 'INVALID_CHAPTER', '章节不属于课程')
    fingerprint = hashlib.sha256(data.model_dump_json().encode() + str(course_id).encode()).hexdigest()
    job_key = f'import:{user.id}:{key}'
    existing = session.scalar(select(ProcessingJob).where(ProcessingJob.idempotency_key == job_key))
    if existing:
        if existing.payload['fingerprint'] != fingerprint:
            raise ApiError(409, 'IDEMPOTENCY_CONFLICT', '导入标识冲突')
        return {'jobId':str(existing.id), 'resourceId':existing.payload['resource_id'], 'versionId':str(existing.resource_version_id)}
    resource = Resource(id=uuid.uuid4(), owner_id=user.id, kind=ALLOWED[data.content_type], display_name=_filename(data.filename))
    session.add(resource)
    session.flush()
    version = ResourceVersion(id=uuid.uuid4(), resource_id=resource.id, version_no=1,
        object_key=f'pending/{resource.id}', content_type=data.content_type, size_bytes=data.size_bytes, state='VALIDATING')
    session.add(version)
    session.flush()
    resource.current_version_id = version.id
    session.add(CourseResource(course_id=course_id, resource_id=resource.id, chapter_id=data.chapter_id, added_by=user.id))
    job = enqueue(session, 'IMPORT_RESOURCE', job_key, version.id,
        {'url':data.url, 'fingerprint':fingerprint, 'expected_sha256':data.sha256,
         'resource_id':str(resource.id), 'course_id':str(course_id)})
    return {'jobId':str(job.id),'resourceId':str(resource.id),'versionId':str(version.id)}
