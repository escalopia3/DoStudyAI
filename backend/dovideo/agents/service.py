import uuid
import os
from datetime import datetime,timedelta,timezone
from sqlalchemy import select,or_,update
from dovideo.models import AgentThread,AgentRun,AgentEvent,User
from dovideo.business.courses import require_owned_course
from dovideo.errors import ApiError

def thread(session,user,course_id):
    require_owned_course(session,course_id,user.id)
    row=AgentThread(id=uuid.uuid4(),user_id=user.id,course_id=course_id)
    session.add(row);return {'thread_id':str(row.id),'course_id':str(course_id)}
def owned(session,user,thread_id):
    row=session.get(AgentThread,thread_id)
    if row is None or row.user_id!=user.id:raise ApiError(404,'THREAD_NOT_FOUND','会话不存在')
    require_owned_course(session,row.course_id,user.id)
    return row
def run(session,user,thread_id,text,model_id=None,request_id=None):
    # Serialize admission across processes. Global lock precedes the user lock.
    from sqlalchemy import text as sql_text,func
    session.execute(sql_text('SELECT pg_advisory_xact_lock(72410219)'))
    session.get(User,user.id,with_for_update=True)
    owned(session,user,thread_id)
    session.get(AgentThread,thread_id,with_for_update=True)
    if not text.strip() or len(text)>10000:raise ApiError(422,'INVALID_MESSAGE','消息无效')
    active=AgentRun.state.in_(['QUEUED','RUNNING'])
    total=session.scalar(select(func.count()).select_from(AgentRun).where(active))
    count=session.scalar(select(func.count()).select_from(AgentRun).join(AgentThread,
        AgentThread.id==AgentRun.thread_id).where(active,AgentThread.user_id==user.id))
    if total>=int(os.getenv('DOVIDEO_MAX_ACTIVE_RUNS','32')) or count>=int(os.getenv('DOVIDEO_MAX_USER_RUNS','2')):
        raise ApiError(429,'RUN_CAPACITY_EXCEEDED','当前任务较多，请稍后重试')
    daily=session.scalar(select(func.count()).select_from(AgentRun).join(AgentThread,
        AgentThread.id==AgentRun.thread_id).where(AgentThread.user_id==user.id,
        AgentRun.created_at>=datetime.now(timezone.utc)-timedelta(hours=24)))
    if daily>=int(os.getenv('DOVIDEO_MAX_USER_DAILY_RUNS','200')):
        raise ApiError(429,'RUN_QUOTA_EXCEEDED','已达到每日问答用量上限')
    if session.scalar(select(AgentRun.id).where(AgentRun.thread_id==thread_id,AgentRun.state.in_(['QUEUED','RUNNING']))):
        raise ApiError(409,'THREAD_BUSY','当前会话已有运行')
    row=AgentRun(id=uuid.uuid4(),thread_id=thread_id,input_text=text,model_id=model_id,state='QUEUED',checkpoint={},answer='',usage={},cancel_requested=False,
                 request_id=request_id,max_claim_attempts=max(1,int(os.getenv('DOVIDEO_MAX_CLAIM_ATTEMPTS','3'))))
    session.add(row);session.flush();session.add(AgentEvent(run_id=row.id,kind='run.queued',data={}))
    return {'run_id':str(row.id),'state':row.state}
def get_run(session,user,run_id):
    row=session.get(AgentRun,run_id)
    if row is None:raise ApiError(404,'RUN_NOT_FOUND','运行不存在')
    owned(session,user,row.thread_id)
    return row
def view(row):
    return {'run_id':str(row.id),'thread_id':str(row.thread_id),'state':row.state,'model_id':row.model_id,'answer':row.answer,
            'usage':row.usage,'error_code':row.error_code}
def claim(session):
    now=datetime.now(timezone.utc)
    recoverable=or_(AgentRun.state=='QUEUED',(AgentRun.state=='RUNNING')&(AgentRun.lease_until<now))
    exhausted=session.scalars(select(AgentRun).where(recoverable,or_(
        AgentRun.claim_attempts>=AgentRun.max_claim_attempts,AgentRun.deadline_at<=now))
        .with_for_update(skip_locked=True)).all()
    for item in exhausted:
        item.state='FAILED';item.error_code='RUN_DEADLINE_EXCEEDED' if item.deadline_at and item.deadline_at<=now else 'LEASE_EXHAUSTED'
        item.lease_until=None;item.lease_token=None
        session.add(AgentEvent(run_id=item.id,kind='run.failed',data={'code':item.error_code}))
    session.flush()
    cancelled=session.execute(update(AgentRun).where(AgentRun.state=='RUNNING',
        AgentRun.cancel_requested.is_(True),AgentRun.lease_until<now)
        .values(state='CANCELLED',lease_until=None,lease_token=None).returning(AgentRun.id)).scalars()
    for run_id in cancelled:
        session.add(AgentEvent(run_id=run_id,kind='run.cancelled',data={}))
    row=session.scalar(select(AgentRun).where(AgentRun.cancel_requested.is_(False),
        or_(AgentRun.state=='QUEUED',(AgentRun.state=='RUNNING')&(AgentRun.lease_until<now)))
        .order_by(AgentRun.created_at).with_for_update(skip_locked=True).limit(1))
    if row:
        row.claim_attempts+=1
        if row.started_at is None:
            row.started_at=now
            row.deadline_at=now+timedelta(seconds=max(1,int(os.getenv('DOVIDEO_RUN_DEADLINE_SECONDS','300'))))
        row.state='RUNNING';row.lease_token=str(uuid.uuid4());row.lease_until=now+timedelta(seconds=120)
        session.add(AgentEvent(run_id=row.id,kind='run.started',data={}))
    return row
