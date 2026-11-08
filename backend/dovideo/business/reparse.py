"""Operator refresh of parsed evidence; keep the published index usable until ready."""
import re
from datetime import datetime,timezone
from sqlalchemy import select
from dovideo.business import jobs
from dovideo.errors import ApiError
from dovideo.models import Resource,ResourceVersion,ProcessingJob


def enqueue_refresh(session,user,resource_id,review_sha256):
    resource=session.get(Resource,resource_id,with_for_update=True)
    if resource is None or resource.deleted_at or resource.owner_id!=user.id:
        raise ApiError(404,'RESOURCE_NOT_FOUND','资料不存在')
    if not re.fullmatch('[a-f0-9]{64}',review_sha256):raise ValueError('INVALID_REVIEW_DIGEST')
    version=session.get(ResourceVersion,resource.current_version_id)
    parsed=session.scalar(select(ProcessingJob).where(ProcessingJob.resource_version_id==version.id,
        ProcessingJob.kind=='PROCESS_RESOURCE',ProcessingJob.state=='SUCCEEDED'))
    if parsed is None or not parsed.payload.get('artifacts',{}).get('document.json'):
        raise ApiError(409,'RESOURCE_NOT_PARSED','资料尚未完成解析')
    busy=session.scalar(select(ProcessingJob.id).where(ProcessingJob.resource_version_id==version.id,
        ProcessingJob.kind.in_(['PROCESS_RESOURCE','INDEX_RESOURCE','REFRESH_RESOURCE']),
        ProcessingJob.state.in_(['QUEUED','RUNNING'])))
    if busy:raise ApiError(409,'RESOURCE_BUSY','资料正在处理中')
    key=f'refresh:{version.id}:formulas-v1:{review_sha256}'
    return jobs.enqueue(session,'REFRESH_RESOURCE',key,version.id,{
        'resource_id':str(resource.id),'owner_id':str(user.id),
        'expected_source_sha256':version.checksum_sha256,'formula_review_sha256':review_sha256,
        'canonical_parse_job_id':str(parsed.id),
        'expected_document_sha256':parsed.payload['artifacts']['document.json']['sha256']})


def publish_refresh(session,job,artifacts):
    """CAS the canonical parse pointer, retain history, then enqueue an immutable index."""
    import uuid
    version=session.get(ResourceVersion,job.resource_version_id)
    resource=session.get(Resource,version.resource_id,with_for_update=True)
    canonical=session.get(ProcessingJob,uuid.UUID(job.payload['canonical_parse_job_id']),with_for_update=True)
    if (resource.deleted_at or resource.current_version_id!=version.id
            or version.checksum_sha256!=job.payload['expected_source_sha256']
            or canonical is None or canonical.state!='SUCCEEDED'
            or canonical.payload.get('artifacts',{}).get('document.json',{}).get('sha256')!=job.payload['expected_document_sha256']):
        job.state='FAILED';job.error_code='PARSED_SNAPSHOT_CHANGED';return
    history=list(canonical.payload.get('artifact_history',[]))
    history.append({'artifacts':canonical.payload['artifacts'],'refresh_job_id':str(job.id),
        'replaced_at':datetime.now(timezone.utc).isoformat()})
    canonical.payload=dict(canonical.payload,artifacts=artifacts,artifact_history=history,
        last_refresh={'job_id':str(job.id),'review_sha256':job.payload['formula_review_sha256']})
    job.payload=dict(job.payload,artifacts=artifacts)
    version.state='PARSED'
    session.flush()
    from dovideo.knowledge import enqueue_index
    index_job=enqueue_index(session,resource,version,rebuild=True)
    job.payload=dict(job.payload,index_job_id=str(index_job.id))


def retained_artifact_keys(payload):
    """Retain canonical and historical immutable artifacts across maintenance."""
    keys={a['key'] for a in payload.get('artifacts',{}).values() if isinstance(a,dict) and a.get('key')}
    for entry in payload.get('artifact_history',[]):
        keys.update(a['key'] for a in entry.get('artifacts',{}).values() if isinstance(a,dict) and a.get('key'))
    return keys
