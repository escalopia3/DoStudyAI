"""Knowledge projection shared by worker, HTTP evaluation and future agent tools.

Only the parent worker publishes active pointers. Executors write immutable,
attempt-scoped Qdrant points; PostgreSQL remains the visibility authority.
"""
import hashlib
import io
import json
import os
import threading
import uuid
from functools import lru_cache
from time import perf_counter

from sqlalchemy import select
from qdrant_client import models as qm
from dovideo.config import PROJECT_ROOT, load_local_environment
from dovideo.errors import ApiError
from dovideo.models import (Resource, ResourceVersion, ProcessingJob, CourseResource,
                            KnowledgeIndex, ActiveKnowledgeIndex)
from dovideo.business.courses import require_owned_course
from dovideo.business import jobs
from dovideo.validation import InvalidResource
from knowledge_service.indexing.embedding import LocalBgeM3Config, LocalBgeM3Provider

_model_lock = threading.Lock()

def index_config():
    load_local_environment()
    revision_path = PROJECT_ROOT / '.learning-models/bge-m3.revision.txt'
    revision = os.getenv('DOVIDEO_EMBEDDING_REVISION', '').strip()
    if not revision and revision_path.is_file():
        revision = revision_path.read_text(encoding='utf-8').strip()
    if not revision:
        raise ValueError('EMBEDDING_REVISION_REQUIRED')
    config = LocalBgeM3Config(model_path='', model_revision=revision)
    return {'embeddingVersion': config.version, 'modelRevision': revision, 'dimension':1024,
            'chunkerVersion':'structure-v4', 'childTokens':600, 'parentTokens':1800,
            'outlineVersion':'1', 'parentOverviewVersion':'extractive-v1',
            'maxLength':2048, 'normalize':True, 'sparseModel':'Qdrant/bm25',
            'retrievalVersion':'dense-bm25-rrf-v1'}

def collection_name(config):
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]
    return 'dovideo_knowledge_' + digest

@lru_cache(maxsize=1)
def embedding_provider(config_json):
    config = json.loads(config_json)
    # A revision label cannot turn the single configured directory into an old
    # model. Fail explicitly instead of querying old vectors with new weights.
    if config['modelRevision'] != index_config()['modelRevision']:
        raise ValueError('EMBEDDING_REVISION_UNAVAILABLE_REINDEX_REQUIRED')
    path = os.getenv('DOVIDEO_EMBEDDING_MODEL_PATH', str(PROJECT_ROOT / '.learning-models/bge-m3'))
    return LocalBgeM3Provider(LocalBgeM3Config(model_path=path,
        model_revision=config['modelRevision'], max_length=config['maxLength'],
        device=os.getenv('DOVIDEO_EMBEDDING_DEVICE', 'cpu')))

def embeddings(config, texts):
    # SentenceTransformer is expensive; retain one model in the serving process,
    # and serialize encode/cache access across FastAPI threadpool requests.
    with _model_lock:
        return embedding_provider(json.dumps(config, sort_keys=True)).embed_documents(texts)

def ensure_collection(client, name, dimension):
    if not client.collection_exists(name):
        try:
            client.create_collection(name,
                vectors_config={'dense':qm.VectorParams(size=dimension, distance=qm.Distance.COSINE)},
                sparse_vectors_config={'bm25':qm.SparseVectorParams(modifier=qm.Modifier.IDF)})
        except Exception:
            if not client.collection_exists(name):
                raise
    params = client.get_collection(name).config.params
    dense = params.vectors.get('dense') if isinstance(params.vectors, dict) else None
    if (dense is None or dense.size != dimension or dense.distance != qm.Distance.COSINE
            or not params.sparse_vectors or 'bm25' not in params.sparse_vectors
            or params.sparse_vectors['bm25'].modifier != qm.Modifier.IDF):
        raise InvalidResource('QDRANT_SCHEMA_MISMATCH')
    for key in ('ownerId','resourceId','indexRevision','chunkType'):
        client.create_payload_index(name, key, qm.PayloadSchemaType.KEYWORD, wait=True)

def scope_filter(owner_id=None, pairs=None, index_id=None, resource_id=None, chunk_type=None):
    must = []
    for key, value in [('ownerId',owner_id), ('indexRevision',index_id),
                       ('resourceId',resource_id), ('chunkType',chunk_type)]:
        if value is not None:
            must.append(qm.FieldCondition(key=key, match=qm.MatchValue(value=str(value))))
    if pairs is not None:
        if not pairs:
            raise ValueError('EMPTY_QUERY_SCOPE')
        must.append(qm.Filter(should=[qm.Filter(must=[
            qm.FieldCondition(key='resourceId', match=qm.MatchValue(value=str(r))),
            qm.FieldCondition(key='indexRevision', match=qm.MatchValue(value=str(i)))]) for r,i in pairs]))
    if not must:
        raise ValueError('EMPTY_QUERY_SCOPE')
    return qm.Filter(must=must)

def enqueue_index(session, resource, version, *, rebuild=False):
    parsed = session.scalar(select(ProcessingJob).where(ProcessingJob.resource_version_id == version.id,
        ProcessingJob.kind == 'PROCESS_RESOURCE', ProcessingJob.state == 'SUCCEEDED'))
    if parsed is None or 'document.json' not in parsed.payload.get('artifacts', {}):
        raise ApiError(409, 'RESOURCE_NOT_PARSED', '资料尚未完成解析')
    try:
        config = index_config()
    except ValueError as exc:
        # Parsing remains usable even if indexing configuration is incomplete.
        # The durable index task will expose a permanent, retryable-by-operator
        # configuration failure instead of rolling back a successful parse.
        config = {'configurationError':str(exc)}
    digest = collection_name(config)
    # Serialize with deletion/publication and coalesce concurrent rebuilds.
    active_job = session.scalar(select(ProcessingJob).where(ProcessingJob.resource_version_id == version.id,
        ProcessingJob.kind == 'INDEX_RESOURCE', ProcessingJob.state.in_(['QUEUED','RUNNING'])))
    if active_job:
        return active_job
    active = session.get(ActiveKnowledgeIndex, resource.id)
    suffix = uuid.uuid4().hex if rebuild else digest
    return jobs.enqueue(session, 'INDEX_RESOURCE', f'index:{version.id}:{suffix}', version.id,
        {'resource_id':str(resource.id), 'owner_id':str(resource.owner_id),
         'config':config, 'collection':digest, 'artifact':parsed.payload['artifacts']['document.json'],
         'expected_previous':str(active.index_id) if active else None})

def prepare(session, job, token):
    version = session.get(ResourceVersion, job.resource_version_id)
    resource = session.get(Resource, version.resource_id, with_for_update=True)
    if resource.deleted_at or resource.current_version_id != version.id:
        raise ValueError('RESOURCE_CHANGED')
    index = KnowledgeIndex(id=uuid.UUID(token), resource_id=resource.id,
        resource_version_id=version.id, job_id=job.id, collection=job.payload['collection'],
        config=job.payload['config'], state='BUILDING', manifest={})
    session.add(index)

def build(storage, snapshot):
    if snapshot.get('config',{}).get('configurationError'):
        raise InvalidResource('INDEX_CONFIGURATION_MISSING')
    item = snapshot['artifact']
    response = storage.minio.get_object(storage.bucket, item['key'], version_id=item['version_id'])
    try:
        # Bound deserialization memory even when an artifact is unexpectedly large.
        raw = response.read(128 * 1024 * 1024 + 1)
    finally:
        response.close()
        response.release_conn()
    if len(raw) > 128 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != item['sha256']:
        raise InvalidResource('DOCUMENT_HASH_OR_SIZE_MISMATCH')
    document = json.loads(raw)
    if document.get('schemaVersion') != '1' or document.get('resourceRevisionId') != snapshot['version_id']:
        raise InvalidResource('DOCUMENT_VERSION_MISMATCH')
    config = snapshot['config']
    from dovideo.chunking import build_chunks
    with _model_lock:
        provider = embedding_provider(json.dumps(config, sort_keys=True))
        tokenizer = provider.model.tokenizer
        bundle = build_chunks(document, tokenizer, config['childTokens'], config['parentTokens'])
    chunks = [*bundle.parents, *bundle.children]
    if any(len(tokenizer.encode(c.embeddingText,add_special_tokens=True,truncation=False)) > config['maxLength'] for c in chunks):
        raise InvalidResource('EMBEDDING_INPUT_TOO_LONG')
    client, collection = storage.qdrant, snapshot['collection']
    ensure_collection(client, collection, config['dimension'])
    index_id = snapshot['lease_token']
    for start in range(0, len(chunks), 16):
        batch = chunks[start:start+16]
        vectors = embeddings(config, [c.embeddingText for c in batch])
        client.upsert(collection, points=[qm.PointStruct(
            id=str(uuid.uuid5(uuid.UUID(index_id), c.chunkId)),
            vector={'dense':v, 'bm25':qm.Document(text=c.embeddingText, model=config['sparseModel'])},
            payload=c.to_dict() | {'resourceId':snapshot['resource_id'], 'ownerId':snapshot['owner_id'],
                'sourceRevision':snapshot['version_id'], 'indexRevision':index_id,
                'embeddingVersion':config['embeddingVersion'], 'documentName':document.get('name','')})
            for c,v in zip(batch,vectors)], wait=True)
    filt = scope_filter(index_id=index_id, resource_id=snapshot['resource_id'])
    count = client.count(collection, count_filter=filt, exact=True).count
    if count != len(chunks):
        raise InvalidResource('QDRANT_POINT_COUNT_MISMATCH')
    known = {c.chunkId:c.contentHash for c in chunks}
    samples, _ = client.scroll(collection, scroll_filter=filt, limit=min(10,len(chunks)), with_vectors=False)
    if any(known.get(p.payload.get('chunkId')) != p.payload.get('contentHash') for p in samples):
        raise InvalidResource('QDRANT_CONTENT_MISMATCH')
    manifest = {'schemaVersion':'1', 'indexRevision':index_id, 'sourceRevision':snapshot['version_id'],
                'pointCount':count, 'parentCount':len(bundle.parents), 'childCount':len(bundle.children),
                'config':config, 'documentSha256':item['sha256'],'documentArtifact':dict(item),
                'parser':document.get('parser',{}),
                'chunksSha256':hashlib.sha256(json.dumps(sorted(known.items())).encode()).hexdigest()}
    artifacts = {}
    from dovideo.knowledge_artifacts import make_outline
    for name, value in [('chunks.json',bundle.to_dict()), ('outline.json',make_outline(bundle))]:
        body = json.dumps(value,ensure_ascii=False).encode()
        object_key = f"indexes/{snapshot['version_id']}/{index_id}/{name}"
        uploaded = storage.minio.put_object(storage.bucket,object_key,io.BytesIO(body),len(body),content_type='application/json')
        artifacts[name] = {'key':object_key,'version_id':uploaded.version_id,'sha256':hashlib.sha256(body).hexdigest()}
    manifest['artifacts'] = artifacts
    manifest['qualityFlags'] = document.get('qualityFlags',[])
    data = json.dumps(manifest, ensure_ascii=False).encode()
    key = f"indexes/{snapshot['version_id']}/{index_id}/manifest.json"
    result = storage.minio.put_object(storage.bucket, key, io.BytesIO(data), len(data), content_type='application/json')
    return {'ok':True, 'manifest':manifest, 'artifact':{'key':key,'version_id':result.version_id,
            'sha256':hashlib.sha256(data).hexdigest()}}

def publish(session, job, token, result):
    version = session.get(ResourceVersion, job.resource_version_id)
    resource = session.get(Resource, version.resource_id, with_for_update=True)
    index = session.get(KnowledgeIndex, uuid.UUID(token))
    active = session.get(ActiveKnowledgeIndex, resource.id)
    previous = str(active.index_id) if active else None
    if resource.deleted_at or resource.current_version_id != version.id or previous != job.payload['expected_previous']:
        index.state = 'SUPERSEDED'
        job.state, job.error_code = 'FAILED', 'INDEX_PUBLICATION_CONFLICT'
        return
    if active:
        session.get(KnowledgeIndex, active.index_id).state = 'RETIRED'
        active.index_id = index.id
    else:
        session.add(ActiveKnowledgeIndex(resource_id=resource.id, index_id=index.id))
    index.state = 'PUBLISHED'
    index.manifest = dict(result['manifest'], artifact=result['artifact'])
    job.payload = dict(job.payload, manifest=result['manifest'])

def authorized_indexes(session, user, course_id):
    require_owned_course(session, course_id, user.id)
    return session.execute(select(Resource, KnowledgeIndex).join(CourseResource,
        CourseResource.resource_id == Resource.id).join(ActiveKnowledgeIndex,
        ActiveKnowledgeIndex.resource_id == Resource.id).join(KnowledgeIndex,
        KnowledgeIndex.id == ActiveKnowledgeIndex.index_id).where(
        CourseResource.course_id == course_id, Resource.owner_id == user.id,
        Resource.deleted_at.is_(None), KnowledgeIndex.state == 'PUBLISHED',
        KnowledgeIndex.resource_version_id == Resource.current_version_id)).all()

def search(session, storage, user, course_id, question, limit=8):
    if not isinstance(question,str) or not 1 <= len(question.strip()) <= 2000 or not 1 <= limit <= 30:
        raise ApiError(422,'INVALID_QUERY','检索参数无效')
    started = perf_counter()
    rows = authorized_indexes(session, user, course_id)
    grouped = {}
    for resource,index in rows:
        grouped.setdefault(index.collection, []).append((resource,index))
    hits = []
    for collection, group in grouped.items():
        config = group[0][1].config
        if config['modelRevision'] != index_config()['modelRevision']:
            raise ApiError(409,'KNOWLEDGE_REINDEX_REQUIRED','本地Embedding版本已变化，请重建课程资料索引')
        vector = embeddings(config, [question])[0]
        filt = scope_filter(owner_id=user.id, pairs=[(r.id,i.id) for r,i in group], chunk_type='CHILD')
        response = storage.qdrant.query_points(collection, prefetch=[
            qm.Prefetch(query=vector, using='dense', filter=filt, limit=max(30,limit)),
            qm.Prefetch(query=qm.Document(text=question, model=config['sparseModel']),
                        using='bm25', filter=filt, limit=max(30,limit))],
            query=qm.FusionQuery(fusion=qm.Fusion.RRF), limit=limit, with_payload=True)
        hits.extend((1.0/(60+rank), point) for rank,point in enumerate(response.points, 1))
    # Different embedding generations have independently fused rankings. Merge
    # by rank rather than comparing unrelated numeric similarity scores.
    hits.sort(key=lambda item:item[0], reverse=True)
    # Revalidate after model execution/network I/O: deletion or replacement may
    # have committed while this request was searching.
    rows = authorized_indexes(session, user, course_id)
    snapshot = hashlib.sha256('\0'.join(sorted(str(i.id) for _,i in rows)).encode()).hexdigest()
    evidence = []
    allowed = {(str(r.id),str(i.id)) for r,i in rows}
    for _,hit in hits:
        p = hit.payload
        if (p.get('resourceId'),p.get('indexRevision')) not in allowed or p.get('ownerId') != str(user.id):
            continue
        evidence.append({'sourceId':f'S{len(evidence)+1}', 'resourceId':p['resourceId'],
            'sourceRevision':p['sourceRevision'], 'indexRevision':p['indexRevision'],
            'chunkId':p['chunkId'], 'parentId':p.get('parentId'), 'content':p['content'],
            'contentHash':p['contentHash'], 'documentName':p.get('documentName',''),
            'titlePath':p.get('titlePath',[]), 'locators':p.get('locators',[]), 'score':hit.score})
        if len(evidence) == limit:
            break
    parents = []
    for collection,group in grouped.items():
        indexes = {str(index.id) for _,index in group}
        keys = list(dict.fromkeys((e['indexRevision'],e['parentId']) for e in evidence
                    if e['indexRevision'] in indexes and e.get('parentId')))[:5]
        if not keys:
            continue
        points = storage.qdrant.retrieve(collection,
            ids=[str(uuid.uuid5(uuid.UUID(index_id),parent_id)) for index_id,parent_id in keys],with_vectors=False)
        for point in points:
            p = point.payload
            if (p.get('resourceId'),p.get('indexRevision')) in allowed and p.get('ownerId') == str(user.id):
                parents.append({'resourceId':p['resourceId'], 'indexRevision':p['indexRevision'],
                    'parentId':p['chunkId'], 'content':p['content'], 'titlePath':p.get('titlePath',[]),
                    'locators':p.get('locators',[])})
    final_ids = {str(i.id) for _,i in authorized_indexes(session,user,course_id)}
    rows = [(r,i) for r,i in rows if str(i.id) in final_ids]
    evidence = [e for e in evidence if e['indexRevision'] in final_ids]
    parents = [p for p in parents if p['indexRevision'] in final_ids]
    for n,item in enumerate(evidence,1):
        item['sourceId'] = f'S{n}'
    snapshot = hashlib.sha256('\0'.join(sorted(str(i.id) for _,i in rows)).encode()).hexdigest()
    return {'knowledgeSnapshotId':snapshot, 'evidence':evidence, 'parentEvidence':parents[:5], 'indexedResourceCount':len(rows),
            'elapsedMs':round((perf_counter()-started)*1000,2)}

def rebuild(session, user, resource_id):
    resource = session.get(Resource, resource_id, with_for_update=True)
    if resource is None or resource.owner_id != user.id or resource.deleted_at:
        raise ApiError(404, 'RESOURCE_NOT_FOUND', '资料不存在')
    version = session.get(ResourceVersion, resource.current_version_id)
    job = enqueue_index(session, resource, version, rebuild=True)
    return {'jobId':str(job.id), 'state':job.state}

def status(session, user, course_id):
    require_owned_course(session, course_id, user.id)
    rows = session.execute(select(Resource, ResourceVersion).join(CourseResource,
        CourseResource.resource_id == Resource.id).join(ResourceVersion,
        ResourceVersion.id == Resource.current_version_id).where(CourseResource.course_id == course_id,
            Resource.owner_id == user.id, Resource.deleted_at.is_(None))).all()
    result = []
    for resource,version in rows:
        active = session.get(ActiveKnowledgeIndex, resource.id)
        job = session.scalar(select(ProcessingJob).where(ProcessingJob.resource_version_id == version.id,
            ProcessingJob.kind == 'INDEX_RESOURCE').order_by(ProcessingJob.created_at.desc()).limit(1))
        result.append({'resourceId':str(resource.id), 'parseState':version.state,
            'activeIndexId':str(active.index_id) if active else None,
            'indexJobId':str(job.id) if job else None, 'indexState':job.state if job else 'NOT_STARTED',
            'errorCode':job.error_code if job else None})
    return {'items':result}
