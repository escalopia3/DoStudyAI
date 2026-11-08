"""Immutable, hash-checked index content. Authorization belongs to the caller."""
import hashlib
import json
from dovideo.errors import ApiError

def section_id(path):
    return 'section-' + hashlib.sha256(json.dumps(path,ensure_ascii=False).encode()).hexdigest()[:24]

def make_outline(bundle):
    sections = {}
    for parent in bundle.parents:
        sid = section_id(parent.titlePath)
        sections.setdefault(sid,{'section_id':sid,'title_path':parent.titlePath,'parent_ids':[]})['parent_ids'].append(parent.chunkId)
    return {'sections':list(sections.values()),'resource_version_id':bundle.resourceRevisionId}

def read(storage,index,name):
    item = index.manifest.get('artifacts',{}).get(name)
    if not item:
        raise ApiError(409,'KNOWLEDGE_REINDEX_REQUIRED','该索引缺少目录产物，请重建')
    response = storage.minio.get_object(storage.bucket,item['key'],version_id=item['version_id'])
    try:
        raw = response.read(128*1024*1024+1)
    finally:
        response.close()
        response.release_conn()
    if len(raw)>128*1024*1024 or hashlib.sha256(raw).hexdigest()!=item['sha256']:
        raise ApiError(503,'INDEX_ARTIFACT_INVALID','索引产物校验失败')
    return json.loads(raw)
