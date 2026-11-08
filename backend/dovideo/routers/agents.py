import uuid
import asyncio
import json
from fastapi import APIRouter,Depends,Header,Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field,ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from dovideo.dependencies import current_user,get_session
from dovideo.models import AgentEvent,AgentRun,AgentThread
from dovideo.models import LearningPreference,LearningMemory,PracticeAttempt,PracticeQuestion,User
from dovideo.errors import ApiError
from dovideo.business.courses import require_owned_course
from dovideo.agents import service

router=APIRouter(prefix='/api/v2',tags=['agent'])
class RunInput(BaseModel):
    message:str=Field(min_length=1,max_length=10000)
    model_id:str|None=Field(default=None,max_length=100)
class PreferenceInput(BaseModel):
    value:str=Field(min_length=1,max_length=300)
class MemoryInput(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True)
    kind:str=Field(pattern='^(goal|difficulty|progress|note)$')
    content:str=Field(min_length=1,max_length=500)
    course_id:uuid.UUID|None=None
class AttemptInput(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    question_id:uuid.UUID
    submitted_answer:str=Field(min_length=1,max_length=1000)
class MemoryReview(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True)
    content:str=Field(min_length=1,max_length=500)
@router.get('/learning-memories')
def list_memories(course_id:uuid.UUID|None=None,session:Session=Depends(get_session),user=Depends(current_user)):
    if course_id:require_owned_course(session,course_id,user.id)
    query=select(LearningMemory).where(LearningMemory.user_id==user.id,LearningMemory.status.in_(['pending','confirmed']))
    if course_id:query=query.where((LearningMemory.course_id==course_id)|(LearningMemory.course_id.is_(None)))
    rows=session.scalars(query.order_by(LearningMemory.created_at.desc()).limit(100)).all()
    return {'items':[{'id':str(r.id),'kind':r.kind,'content':r.content,'status':r.status,'revision':r.revision,
        'automatic':bool(r.origin and r.origin.get('method','').startswith('explicit_user')),
        'course_id':str(r.course_id) if r.course_id else None} for r in rows]}
@router.put('/learning-memories/{memory_id}')
def review_memory(memory_id:uuid.UUID,data:MemoryReview,session:Session=Depends(get_session),user=Depends(current_user)):
    session.get(User,user.id,with_for_update=True)
    row=session.get(LearningMemory,memory_id)
    if row is None or row.user_id!=user.id or row.status not in ('pending','confirmed'):raise ApiError(404,'MEMORY_NOT_FOUND','学习记录不存在')
    if row.fact_key and row.content!=data.content:
        previous=row;previous.status='superseded';session.flush()
        row=LearningMemory(user_id=user.id,course_id=previous.course_id,kind=previous.kind,
            content=data.content,status='confirmed',fact_key=previous.fact_key,revision=previous.revision+1,
            origin={'method':'manual_edit','supersedes_id':str(previous.id)})
        session.add(row);session.flush()
    else:
        row.content=data.content;row.status='confirmed'
    return {'id':str(row.id),'status':row.status,'content':row.content}
@router.post('/learning-memories',status_code=201)
def add_memory(data:MemoryInput,session:Session=Depends(get_session),user=Depends(current_user)):
    session.get(User,user.id,with_for_update=True)
    if data.course_id:require_owned_course(session,data.course_id,user.id)
    row=LearningMemory(user_id=user.id,course_id=data.course_id,kind=data.kind,content=data.content.strip())
    session.add(row);session.flush()
    return {'id':str(row.id),'kind':row.kind,'content':row.content}
@router.delete('/learning-memories/{memory_id}',status_code=204)
def delete_memory(memory_id:uuid.UUID,session:Session=Depends(get_session),user=Depends(current_user)):
    from dovideo.errors import ApiError
    session.get(User,user.id,with_for_update=True)
    row=session.get(LearningMemory,memory_id)
    if row is None or row.user_id!=user.id:raise ApiError(404,'MEMORY_NOT_FOUND','学习记录不存在')
    records=session.scalars(select(LearningMemory).where(LearningMemory.user_id==user.id,
        LearningMemory.course_id==row.course_id,LearningMemory.fact_key==row.fact_key)).all() if row.fact_key else [row]
    # Keep an empty tombstone for run idempotency; erase facts and source text in every version.
    for item in records:item.status='deleted';item.content='';item.origin={}
@router.post('/courses/{course_id}/practice-attempts',status_code=201)
def practice_attempt(course_id:uuid.UUID,data:AttemptInput,session:Session=Depends(get_session),user=Depends(current_user)):
    require_owned_course(session,course_id,user.id)
    question=session.scalar(select(PracticeQuestion).join(AgentRun,AgentRun.id==PracticeQuestion.run_id)
        .join(AgentThread,AgentThread.id==AgentRun.thread_id).where(PracticeQuestion.id==data.question_id,
        AgentThread.user_id==user.id,AgentThread.course_id==course_id,AgentRun.state=='SUCCEEDED'))
    if question is None:raise ApiError(404,'QUESTION_NOT_FOUND','练习题不存在')
    correct=' '.join(question.expected_answer.split()).casefold()==' '.join(data.submitted_answer.split()).casefold()
    feedback={}
    if getattr(question,'rubric',None):
        from dovideo.agents.provider import ChatModel
        from dovideo.agents.grading import grade
        try:
            feedback=grade(ChatModel(),question,data.submitted_answer)
        except Exception as exc:
            raise ApiError(503,'PRACTICE_REVIEW_UNAVAILABLE','暂时无法评阅，请稍后重试。') from exc
        correct=all(feedback['met'])
    row=PracticeAttempt(user_id=user.id,course_id=course_id,question=question.question,question_id=question.id,
        expected_answer=question.expected_answer,submitted_answer=data.submitted_answer,
        correct=correct,source_ids=[e['source_id'] for e in question.evidence],feedback=feedback)
    session.add(row);session.flush()
    return {'id':str(row.id),'correct':correct,'grading':'rubric' if feedback else 'exact_normalized',
            'expected_answer':question.expected_answer,**feedback}
@router.get('/courses/{course_id}/practice-questions')
def practice_questions(course_id:uuid.UUID,session:Session=Depends(get_session),user=Depends(current_user)):
    require_owned_course(session,course_id,user.id)
    rows=session.scalars(select(PracticeQuestion).join(AgentRun,AgentRun.id==PracticeQuestion.run_id)
        .join(AgentThread,AgentThread.id==AgentRun.thread_id).where(AgentThread.user_id==user.id,
        AgentThread.course_id==course_id,AgentRun.state=='SUCCEEDED')
        .order_by(AgentRun.created_at.desc(), PracticeQuestion.id)).all()
    attempts = session.scalars(select(PracticeAttempt).where(
        PracticeAttempt.user_id == user.id, PracticeAttempt.course_id == course_id,
        PracticeAttempt.question_id.is_not(None)
    ).distinct(PracticeAttempt.question_id).order_by(
        PracticeAttempt.question_id, PracticeAttempt.created_at.desc(), PracticeAttempt.id.desc()
    ))
    latest = {attempt.question_id: {
        'submitted_answer': attempt.submitted_answer, 'correct': attempt.correct,
        'expected_answer': attempt.expected_answer, **(attempt.feedback or {})
    } for attempt in attempts}
    return {'items': [{'id': str(q.id), 'question': q.question, 'latest_attempt': latest.get(q.id)} for q in rows]}
@router.get('/courses/{course_id}/practice-attempts')
def practice_history(course_id:uuid.UUID,session:Session=Depends(get_session),user=Depends(current_user)):
    require_owned_course(session,course_id,user.id)
    rows=session.scalars(select(PracticeAttempt).where(PracticeAttempt.course_id==course_id,
        PracticeAttempt.user_id==user.id,PracticeAttempt.question_id.is_not(None)).order_by(PracticeAttempt.created_at.desc()).limit(100)).all()
    return {'items':[{'id':str(r.id),'question':r.question,'submitted_answer':r.submitted_answer,
        'expected_answer':r.expected_answer,'correct':r.correct,'source_ids':r.source_ids,'feedback':r.feedback} for r in rows]}
@router.get('/learning-preferences')
def preferences(session:Session=Depends(get_session),user=Depends(current_user)):
    return {'items':[{'key':p.key,'value':p.value} for p in session.scalars(select(LearningPreference).where(LearningPreference.user_id==user.id))]}
@router.put('/learning-preferences/{key}')
def set_preference(key:str,data:PreferenceInput,session:Session=Depends(get_session),user=Depends(current_user)):
    if key not in ('explanation_style','difficulty','language','study_goal','memory_enabled'):
        from dovideo.errors import ApiError
        raise ApiError(422,'INVALID_PREFERENCE','偏好类型无效')
    if key=='memory_enabled' and data.value not in ('true','false'):raise ApiError(422,'INVALID_PREFERENCE','记忆开关必须为true或false')
    session.get(User,user.id,with_for_update=True)
    row=session.get(LearningPreference,(user.id,key))
    if row:row.value=data.value
    else:session.add(LearningPreference(user_id=user.id,key=key,value=data.value))
    return {'key':key,'value':data.value}
@router.delete('/learning-preferences/{key}')
def remove_preference(key:str,session:Session=Depends(get_session),user=Depends(current_user)):
    session.get(User,user.id,with_for_update=True)
    row=session.get(LearningPreference,(user.id,key))
    if row:session.delete(row)
    return {'deleted':True}
@router.post('/courses/{course_id}/threads',status_code=201)
def create_thread(course_id:uuid.UUID,session:Session=Depends(get_session),user=Depends(current_user)):
    return service.thread(session,user,course_id)
@router.get('/courses/{course_id}/threads')
def list_threads(course_id:uuid.UUID,session:Session=Depends(get_session),user=Depends(current_user)):
    from dovideo.business.courses import require_owned_course
    require_owned_course(session,course_id,user.id)
    rows=session.scalars(select(AgentThread).where(AgentThread.course_id==course_id,
        AgentThread.user_id==user.id).order_by(AgentThread.created_at.desc()).limit(100)).all()
    return {'items':[{'thread_id':str(row.id),'created_at':row.created_at.isoformat()} for row in rows]}
@router.get('/courses/{course_id}/legacy-history')
def legacy_history(course_id:uuid.UUID, offset:int=0, session:Session=Depends(get_session),user=Depends(current_user)):
    from dovideo.models import LegacyStudyRecord
    require_owned_course(session,course_id,user.id)
    if offset<0:raise ApiError(422,'INVALID_OFFSET','历史记录偏移量无效。')
    rows=session.execute(select(LegacyStudyRecord.id,LegacyStudyRecord.kind,LegacyStudyRecord.title,
        LegacyStudyRecord.occurred_at).where(LegacyStudyRecord.course_id==course_id)
        .order_by(LegacyStudyRecord.occurred_at.desc(),LegacyStudyRecord.id).offset(offset).limit(21)).all()
    return {'items':[dict(row._mapping) for row in rows[:20]],'next_offset':offset+20 if len(rows)>20 else None}

@router.get('/courses/{course_id}/legacy-history/{record_id}')
def legacy_history_detail(course_id:uuid.UUID,record_id:uuid.UUID,session:Session=Depends(get_session),user=Depends(current_user)):
    from dovideo.models import LegacyStudyRecord
    require_owned_course(session,course_id,user.id)
    record=session.scalar(select(LegacyStudyRecord).where(LegacyStudyRecord.id==record_id,
        LegacyStudyRecord.course_id==course_id))
    if record is None:raise ApiError(404,'LEGACY_RECORD_NOT_FOUND','找不到该历史记录。')
    return record.payload

@router.get('/agent/capabilities')
def capabilities(user=Depends(current_user)):
    import os
    missing=[key for key in ('DOVIDEO_CHAT_MODEL','DOVIDEO_CHAT_BASE_URL','DOVIDEO_CHAT_API_KEY')
             if not os.getenv(key,'').strip()]
    return {'model_configured':not missing,'model_id':os.getenv('DOVIDEO_CHAT_MODEL') if not missing else None,
            'missing_model_settings':missing}
@router.post('/threads/{thread_id}/runs',status_code=202)
def create_run(thread_id:uuid.UUID,data:RunInput,request:Request,session:Session=Depends(get_session),user=Depends(current_user)):
    if not capabilities(user)['model_configured']:
        raise ApiError(503,'CHAT_MODEL_NOT_CONFIGURED','聊天模型尚未配置，暂时无法发送消息。')
    return service.run(session,user,thread_id,data.message,data.model_id,request.state.request_id)
@router.get('/runs/{run_id}')
def get_run(run_id:uuid.UUID,session:Session=Depends(get_session),user=Depends(current_user)):
    return service.view(service.get_run(session,user,run_id))
@router.post('/runs/{run_id}/cancel')
def cancel(run_id:uuid.UUID,session:Session=Depends(get_session),user=Depends(current_user)):
    row=service.get_run(session,user,run_id)
    row.cancel_requested=True
    if row.state=='QUEUED':row.state='CANCELLED'
    session.add(AgentEvent(run_id=run_id,kind='run.cancel_requested',data={}))
    return service.view(row)
@router.get('/threads/{thread_id}/messages')
def messages(thread_id:uuid.UUID,session:Session=Depends(get_session),user=Depends(current_user)):
    service.owned(session,user,thread_id)
    rows=session.scalars(select(AgentRun).where(AgentRun.thread_id==thread_id).order_by(AgentRun.created_at)).all()
    practice_ids = {}
    for run_id, question_id in session.execute(
        select(PracticeQuestion.run_id, PracticeQuestion.id)
        .join(AgentRun, AgentRun.id == PracticeQuestion.run_id)
        .where(AgentRun.thread_id == thread_id, AgentRun.state == 'SUCCEEDED')
        .order_by(PracticeQuestion.id)
    ):
        practice_ids.setdefault(run_id, []).append(str(question_id))
    return {'items':[{'run_id':str(r.id),'user':r.input_text,'assistant':r.answer,'state':r.state,'error_code':r.error_code,
        'references':public_references(r), 'practice_question_ids': practice_ids.get(r.id, [])} for r in rows]}

def public_references(run):
    import re
    refs=(run.checkpoint or {}).get('references',{})
    visible=(run.checkpoint or {}).get('citation_evidence')
    result=[]
    for key in dict.fromkeys(re.findall(r'\bS[0-9]+\b',run.answer or '')):
        validation=(run.checkpoint or {}).get('citation_validation',{})
        if validation.get('failed'):continue
        item=refs.get(key)
        if not isinstance(item,dict) or not item.get('resource_id'):continue
        if visible is not None and key not in visible:continue
        pages=sorted({loc['pageIndex']+1 for loc in item.get('locators',[])
                      if isinstance(loc,dict) and type(loc.get('pageIndex')) is int and loc['pageIndex']>=0})
        if visible is not None:pages=visible[key].get('pages',[])
        result.append({'id':key,'resource_id':item['resource_id'],'title_path':item.get('title_path',[]),
                       'pages':pages[:20]})
    return result
@router.get('/runs/{run_id}/events')
def events(run_id:uuid.UUID,session:Session=Depends(get_session),user=Depends(current_user),
           last_event_id:str|None=Header(default=None,alias='Last-Event-ID')):
    service.get_run(session,user,run_id)
    cursor=int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    engine=session.bind
    async def stream():
        nonlocal cursor
        for _ in range(600):
            with Session(engine) as db:
                rows=db.scalars(select(AgentEvent).where(AgentEvent.run_id==run_id,AgentEvent.id>cursor)
                    .order_by(AgentEvent.id).limit(500)).all()
                state=db.get(AgentRun,run_id).state
            for row in rows:
                cursor=row.id
                if row.kind.startswith('private.'):continue
                yield f'id: {row.id}\nevent: {row.kind}\ndata: {json.dumps(row.data,ensure_ascii=False)}\n\n'
            if state in ('SUCCEEDED','FAILED','CANCELLED') and not rows:break
            await asyncio.sleep(1)
    return StreamingResponse(stream(),media_type='text/event-stream')
