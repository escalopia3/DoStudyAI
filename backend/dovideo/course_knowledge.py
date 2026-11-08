"""Single course knowledge entry point; trusted identity and budgets are injected."""
import base64
import hashlib
import json
import os
import uuid
from sqlalchemy import select
from qdrant_client import models as qm
from dovideo import knowledge as k
from dovideo.knowledge_artifacts import read, section_id
from dovideo.errors import ApiError
from dovideo.models import Resource, CourseResource, ResourceVersion, CourseChapter

def query_course_knowledge(session,storage,user,course_id,query='',intent='auto',
                           resource_ids=(),section_ids=(),cursor=None,token_budget=4096,limit=8,page_units=None,
                           debug=None):
    if intent not in ('auto','detail','overview') or not 2048<=token_budget<=16000 or not 1<=limit<=30:
        raise ApiError(422,'INVALID_QUERY','查询参数无效')
    selection_mode=os.getenv('DOVIDEO_DETAIL_EVIDENCE_MODE','parent')
    if selection_mode not in ('parent','child'):raise ValueError('INVALID_DETAIL_EVIDENCE_MODE')
    rows = k.authorized_indexes(session,user,course_id)
    available = {str(r.id) for r,i in rows}
    owned = session.execute(select(Resource,ResourceVersion,CourseResource.chapter_id).join(CourseResource,
        CourseResource.resource_id==Resource.id).join(ResourceVersion,ResourceVersion.id==Resource.current_version_id)
        .where(CourseResource.course_id==course_id,Resource.owner_id==user.id,Resource.deleted_at.is_(None))).all()
    requested = {str(x) for x in resource_ids}
    if requested - {str(r.id) for r,v,c in owned}:
        raise ApiError(404,'RESOURCE_NOT_FOUND','请求范围包含不可访问资料')
    rows = [(r,i) for r,i in rows if not requested or str(r.id) in requested]
    unavailable = [str(r.id) for r,v,c in owned if str(r.id) not in available and (not requested or str(r.id) in requested)]
    scope = {'course':str(course_id),'user':str(user.id),'resources':sorted(requested),
        'sections':sorted(section_ids),'query':query,'intent':intent,'budget':token_budget,'limit':limit,
        'selection_version':selection_mode+'-formula-v2'}
    fingerprint = hashlib.sha256(json.dumps(scope,sort_keys=True).encode()).hexdigest()
    snapshot = hashlib.sha256('\0'.join(sorted(str(i.id) for r,i in rows)).encode()).hexdigest()
    offset = 0
    if cursor:
        try:
            data = json.loads(base64.urlsafe_b64decode(cursor))
            if data['scope']!=fingerprint or data['snapshot']!=snapshot:
                raise ValueError()
            offset = data['offset']
            if type(offset) is not int or offset<0: raise ValueError()
        except Exception:
            raise ApiError(409,'CURSOR_SCOPE_OR_SNAPSHOT_CHANGED','查询范围或索引已变化，请重新开始')
    bundles, outline, valid_sections = {}, [], set()
    for resource,index in sorted(rows,key=lambda row:str(row[0].id)):
        directory = read(storage,index,'outline.json')
        for section in directory['sections']:
            valid_sections.add(section['section_id'])
            outline.append(dict(section,resource_id=str(resource.id),resource_version_id=str(index.resource_version_id)))
        bundles[str(index.id)] = (resource,index,read(storage,index,'chunks.json'))
    if set(section_ids)-valid_sections:
        raise ApiError(404,'SECTION_NOT_FOUND','章节不存在于授权范围')
    # Explicit scopes and unique heading matches select sequential reading.
    matched = {o['section_id'] for o in outline if query.strip() and any(
        title.strip() and (query.strip() in title or title in query) for title in o['title_path'])}
    selected = set(section_ids)
    if intent=='overview' and not selected and matched:
        selected = matched
    if intent=='overview' and query.strip() and not selected and not requested:
        chapters=session.scalars(select(CourseChapter).where(CourseChapter.course_id==course_id)).all()
        chapter_ids={c.id for c in chapters if c.name and c.name in query}
        if not chapter_ids:
            raise ApiError(409,'READING_SCOPE_REQUIRED','请从返回目录选择明确章节或资料范围')
        resource_scope={str(r.id) for r,v,c in owned if c in chapter_ids}
        bundles={key:value for key,value in bundles.items() if str(value[0].id) in resource_scope}
        unavailable=[str(r.id) for r,v,c in owned if c in chapter_ids and str(r.id) not in available]
    mode = 'overview' if intent=='overview' or (intent=='auto' and (selected or not query.strip())) else 'detail'
    if debug is not None:
        debug.update(query=query,intent=intent,mode=mode,limit=limit,token_budget=token_budget,
            page_units=page_units,cursor=cursor,knowledge_snapshot_id=snapshot,
            resource_names={str(r.id):getattr(r,'display_name','') for r,i in rows},
            global_hits=[],parent_recall=[],supplement_hits=[])
    candidates = []
    if mode=='overview':
        for resource,index,bundle in bundles.values():
            candidates.extend((resource,index,c) for c in bundle['children']
                if not selected or section_id(c['titlePath']) in selected)
    else:
        if not query.strip(): raise ApiError(422,'INVALID_QUERY','细节检索需要问题')
        global_result = k.search(session,storage,user,course_id,query,limit)
        if debug is not None:
            debug['global_hits']=[dict(e,rank=n,score_type='qdrant_rrf',
                ordering='collection_rank_fusion') for n,e in enumerate(global_result['evidence'],1)]
        ranks = {e['chunkId']:n for n,e in enumerate(global_result['evidence'])}
        # Parent topic recall supplements, rather than gates, global child recall.
        for resource,index,bundle in bundles.values():
            vector = k.embeddings(index.config,[query])[0]
            filt = k.scope_filter(owner_id=user.id,pairs=[(resource.id,index.id)],chunk_type='PARENT')
            parents = storage.qdrant.query_points(index.collection,prefetch=[
                qm.Prefetch(query=vector,using='dense',filter=filt,limit=10),
                qm.Prefetch(query=qm.Document(text=query,model=index.config['sparseModel']),using='bm25',filter=filt,limit=10)],
                query=qm.FusionQuery(fusion=qm.Fusion.RRF),limit=3).points
            parent_ids={p.payload['chunkId'] for p in parents}
            child_filter=k.scope_filter(owner_id=user.id,pairs=[(resource.id,index.id)],chunk_type='CHILD')
            child_filter.must.append(qm.FieldCondition(key='parentId',match=qm.MatchAny(any=list(parent_ids))))
            extra=storage.qdrant.query_points(index.collection,query=vector,using='dense',query_filter=child_filter,limit=limit).points if parent_ids else []
            if debug is not None:
                debug['parent_recall'].extend({'resource_id':str(resource.id),'rank':n,
                    'chunk_id':p.payload['chunkId'],'score':p.score,'score_type':'qdrant_rrf'}
                    for n,p in enumerate(parents,1))
                debug['supplement_hits'].extend({'resource_id':str(resource.id),'rank':n,
                    'chunk_id':p.payload['chunkId'],'score':p.score,'score_type':'dense_similarity'}
                    for n,p in enumerate(extra,1))
            local_ranks = dict(ranks)
            for n,hit in enumerate(extra):
                local_ranks.setdefault(hit.payload['chunkId'],limit+n)
                ranks.setdefault(hit.payload['chunkId'],limit+n)
            for child in bundle['children']:
                if child['chunkId'] in local_ranks and (not selected or section_id(child['titlePath']) in selected):
                    candidates.append((resource,index,child))
        candidates.sort(key=lambda entry:ranks.get(entry[2]['chunkId'],limit))
        candidates=candidates[:limit]
    if debug is not None:
        debug['ranked_candidates']=[{'rank':n,'resource_id':str(r.id),
            'document_name':getattr(r,'display_name',''),'index_version_id':str(i.id),
            'resource_version_id':str(i.resource_version_id),'chunk_id':c['chunkId'],
            'parent_id':c['parentId'],'content':c['content'],'title_path':c['titlePath'],
            'locators':c['locators'],'selection':'before_cursor' if n<=offset else 'not_processed'}
            for n,(r,i,c) in enumerate(candidates,1)]
    count = lambda text: len(k.embedding_provider(json.dumps(rows[0][1].config,sort_keys=True)).model.tokenizer.encode(text,add_special_tokens=False)) if rows else 0
    evidence,used,seen = [],0,set()
    position=offset
    while position<len(candidates):
        if page_units is not None and len(evidence)>=page_units:
            if debug is not None:
                for item in debug['ranked_candidates'][position:]:item['selection']='page_limit'
            break
        resource,index,child=candidates[position]
        bundle=bundles[str(index.id)][2]
        parent=next(p for p in bundle['parents'] if p['chunkId']==child['parentId'])
        content=child['content']
        expanded=False
        # Child-first remains opt-in: frozen replay did not pass the quality gate.
        # Both policies retain parent recall and sequential overview behavior.
        if mode=='detail' and selection_mode=='parent' and child.get('elementType')!='FORMULA' and parent['chunkId'] not in seen and count(parent['content'])+used<=token_budget:
            content=parent['content'];expanded=True
        key=parent['chunkId'] if expanded else child['chunkId']
        if parent['chunkId'] in seen or key in seen:
            if debug is not None:debug['ranked_candidates'][position]['selection']='deduplicated'
            position+=1; continue
        cost=count(content)
        if used+cost>token_budget:
            if debug is not None:
                for item in debug['ranked_candidates'][position:]:item['selection']='token_budget'
            break
        evidence.append({'source_id':f'S{len(evidence)+1}','resource_id':str(resource.id),
            'document_name':getattr(resource,'display_name',''),
            'resource_version_id':str(index.resource_version_id),'index_version_id':str(index.id),
            'section_id':section_id(child['titlePath']),'chunk_id':child['chunkId'],'parent_id':parent['chunkId'],
            'content':content,'title_path':child['titlePath'],
            'locators':parent['locators'] if expanded else child['locators'],
            'source_element_ids':parent['sourceElementIds'] if expanded else child['sourceElementIds'],
            'source_segments':parent.get('sourceSpans',[]) if expanded else child.get('sourceSpans',[]),
            'expanded':expanded})
        if debug is not None:
            debug['ranked_candidates'][position].update(selection='returned_to_tool',expanded=expanded)
        seen.add(key);used+=cost;position+=1
    current={str(i.id) for r,i in k.authorized_indexes(session,user,course_id)}
    if any(str(i.id) not in current for r,i in rows):
        raise ApiError(409,'KNOWLEDGE_SNAPSHOT_CHANGED','索引已变化，请重新查询')
    next_cursor=None
    if position<len(candidates):
        next_cursor=base64.urlsafe_b64encode(json.dumps({'scope':fingerprint,'snapshot':snapshot,'offset':position}).encode()).decode()
    if debug is not None:
        debug.update(returned_evidence=evidence,token_count=used,next_cursor=next_cursor)
    return {'knowledge_snapshot_id':snapshot,'evidence':evidence,'outline':outline,
        'coverage':{'mode':mode,'scope':scope,'complete':mode=='overview' and next_cursor is None and not unavailable,
                    'returned_units':len(evidence),'total_units':len(candidates),'unavailable_resources':unavailable},
        'next_cursor':next_cursor,'token_count':used,
        'warnings':list(dict.fromkeys((['RETRIEVAL_DOES_NOT_PROVE_ANSWERABILITY'] if mode=='detail' else [])+
            [flag for r,i in rows for flag in i.manifest.get('qualityFlags',[])]))}
