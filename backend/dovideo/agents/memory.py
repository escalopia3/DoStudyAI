"""Scoped, versioned learning facts. PostgreSQL is the visibility authority."""
import time
from sqlalchemy import select
from dovideo.models import LearningMemory,LearningPreference,User
from dovideo.agents.study import memory_facts
from dovideo.agents.recall import relevance,chronological

def enabled(session,user_id):
    setting=session.get(LearningPreference,(user_id,'memory_enabled'))
    return setting is None or setting.value=='true'

def save_explicit(session,user_id,course_id,message,run_id=None):
    facts=memory_facts(message)
    if not facts:return []
    # Serialize same-user writes with API edits/deletes. All write paths use this lock.
    session.get(User,user_id,with_for_update=True)
    if not enabled(session,user_id):return []
    saved=[]
    for fact in facts:
        if fact['kind']=='preference':
            row=session.get(LearningPreference,(user_id,fact['key']))
            if row:row.value=fact['content']
            else:session.add(LearningPreference(user_id=user_id,key=fact['key'],value=fact['content']))
            saved.append({'kind':'preference','key':fact['key']});continue
        previous=session.scalar(select(LearningMemory).where(LearningMemory.user_id==user_id,
            LearningMemory.course_id==course_id,LearningMemory.fact_key==fact['key'],LearningMemory.status=='confirmed').with_for_update())
        if previous and previous.content==fact['content']:
            saved.append({'id':str(previous.id),'kind':previous.kind,'unchanged':True});continue
        # A retried successful run cannot create another version, even after user deletion.
        if run_id and session.scalar(select(LearningMemory.id).where(LearningMemory.user_id==user_id,
            LearningMemory.source_run_id==run_id,LearningMemory.fact_key==fact['key'])):continue
        revision=previous.revision+1 if previous else 1
        if previous:previous.status='superseded';session.flush()
        row=LearningMemory(user_id=user_id,course_id=course_id,kind=fact['kind'],fact_key=fact['key'],
            content=fact['content'],status='confirmed',source_run_id=run_id,revision=revision,
            origin={'method':fact['source'],'source_text':message,'supersedes_id':str(previous.id) if previous else None})
        session.add(row);session.flush();saved.append({'id':str(row.id),'kind':row.kind,'revision':revision})
    return saved

def select_memories(session,user_id,course_id,query,limit=8):
    """Relevance before recency; no new vector service or per-turn model calls."""
    started=time.perf_counter()
    prefs=session.scalars(select(LearningPreference).where(LearningPreference.user_id==user_id,
        LearningPreference.key!='memory_enabled').order_by(LearningPreference.key)).all()
    preferences=['用户明确设置的教学偏好：'+'；'.join(f'{p.key}={p.value}' for p in prefs)] if prefs else []
    if not enabled(session,user_id):return preferences,{'enabled':False,'selected_ids':[]}
    rows=session.scalars(select(LearningMemory).where(LearningMemory.user_id==user_id,
        LearningMemory.status=='confirmed', (LearningMemory.course_id==course_id)|(LearningMemory.course_id.is_(None))))
    goal=any(t in query for t in ('目标','想学','学会'))
    difficulty=any(t in query for t in ('难点','困难','不理解','弄不懂','混淆'))
    progress=any(t in query for t in ('进度','学到','学完','没学'))
    ranked=[];scanned=0
    for row in rows.yield_per(100):
        scanned+=1
        score=relevance(query,row.content)
        if goal and row.kind=='goal':score+=.6
        if difficulty and row.kind=='difficulty':score+=.6
        if progress and row.kind=='progress':score+=.6
        if goal and row.kind!='goal':score*=.1
        if score>.025:ranked.append((score,chronological(row.created_at),str(row.id),row))
    ranked.sort(key=lambda r:(r[0],r[1],r[2]),reverse=True)
    selected=[r[3] for r in ranked[:limit]]
    return preferences+[f'{r.kind}: {r.content}' for r in selected],{
        'enabled':True,'retrieval':'unicode_lexical_and_fact_kind_v1','scanned':scanned,
        'selected_ids':[str(r.id) for r in selected],
        'selected_scores':[round(r[0],5) for r in ranked[:limit]],
        'elapsed_ms':round((time.perf_counter()-started)*1000,3)}
