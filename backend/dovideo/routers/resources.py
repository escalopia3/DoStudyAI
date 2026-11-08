import uuid
from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.orm import Session
from dovideo.business import resources
from dovideo.dependencies import current_user, get_session
from dovideo.schemas import UploadInput, ImportInput

router = APIRouter(prefix="/api/v2", tags=["resources"])

@router.get('/resources/{resource_id}/artifacts/{name}')
def artifact(resource_id: uuid.UUID, name: str, request: Request,
             session=Depends(get_session), user=Depends(current_user)):
    from sqlalchemy import select
    from datetime import timedelta
    from dovideo.models import Resource, ProcessingJob
    from dovideo.errors import ApiError
    resources.download(session, request.app.state.storage, user, resource_id)
    resource = session.get(Resource, resource_id)
    job = session.scalar(select(ProcessingJob).where(ProcessingJob.resource_version_id == resource.current_version_id,
        ProcessingJob.kind == 'PROCESS_RESOURCE', ProcessingJob.state == 'SUCCEEDED'))
    item = job.payload.get('artifacts', {}).get(name) if job else None
    if item is None:
        raise ApiError(404, 'ARTIFACT_NOT_FOUND', '解析产物尚未生成')
    storage = request.app.state.storage
    return {'url':storage.minio.presigned_get_object(storage.bucket, item['key'],
            version_id=item['version_id'], expires=timedelta(minutes=10)), 'sha256':item['sha256']}

@router.post('/courses/{course_id}/resources/imports', status_code=202)
def import_url(course_id: uuid.UUID, data: ImportInput, idempotency_key: str = Header(alias='Idempotency-Key'),
               session=Depends(get_session), user=Depends(current_user)):
    return resources.import_url(session, user, course_id, idempotency_key, data)

@router.post("/courses/{course_id}/resources/uploads", status_code=status.HTTP_201_CREATED)
def initiate_upload(course_id: uuid.UUID, data: UploadInput, request: Request,
                    idempotency_key: str = Header(alias="Idempotency-Key"),
                    session: Session = Depends(get_session), user=Depends(current_user)):
    return resources.initiate(session, request.app.state.storage, request.app.state.settings,
                              user, course_id, idempotency_key, data)

@router.post("/uploads/{upload_id}/complete", status_code=status.HTTP_202_ACCEPTED)
def complete_upload(upload_id: uuid.UUID, request: Request,
                    session: Session = Depends(get_session), user=Depends(current_user)):
    return resources.complete_upload(session, request.app.state.storage, user, upload_id)

@router.get("/courses/{course_id}/resources")
def list_resources(course_id: uuid.UUID, session: Session = Depends(get_session), user=Depends(current_user)):
    return resources.list_resources(session, user, course_id)

@router.get("/resources/{resource_id}/download")
def download(resource_id: uuid.UUID, request: Request,
             session: Session = Depends(get_session), user=Depends(current_user)):
    return resources.download(session, request.app.state.storage, user, resource_id)

@router.get("/jobs/{job_id}")
def job_status(job_id: uuid.UUID, session: Session = Depends(get_session), user=Depends(current_user)):
    return resources.job_status(session, user, job_id)

@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: uuid.UUID, session: Session = Depends(get_session), user=Depends(current_user)):
    return resources.cancel_job(session, user, job_id)

@router.get('/uploads/{upload_id}/parts')
def parts(upload_id: uuid.UUID, request: Request, session=Depends(get_session), user=Depends(current_user)):
    return resources.upload_parts(session, request.app.state.storage, user, upload_id)

@router.post('/uploads/{upload_id}/parts/{number}')
def part_url(upload_id: uuid.UUID, number: int, request: Request, session=Depends(get_session), user=Depends(current_user)):
    return resources.upload_parts(session, request.app.state.storage, user, upload_id, number)

@router.post('/jobs/{job_id}/retry')
def retry(job_id: uuid.UUID, session=Depends(get_session), user=Depends(current_user)):
    return resources.retry_job(session, user, job_id)

@router.delete('/resources/{resource_id}', status_code=202)
def delete_resource(resource_id: uuid.UUID, session=Depends(get_session), user=Depends(current_user)):
    return resources.delete_resource(session, user, resource_id)

@router.post('/uploads/{upload_id}/cancel')
def cancel_upload(upload_id: uuid.UUID, session=Depends(get_session), user=Depends(current_user)):
    return resources.cancel_upload(session, user, upload_id)
