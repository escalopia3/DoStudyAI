"""Opt-in PostgreSQL recovery tests. Never writes to the learning database."""
import os
import uuid
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from dovideo.config import Settings
from dovideo.models import User,Course,AgentThread,AgentRun,AgentEvent,PracticeQuestion
from dovideo.test_isolation import require_test_storage
from dovideo.agents.service import claim
from dovideo.agents.checkpoints import fingerprint
from dovideo.tools.registry import execute
from app.agent_worker import run_once

pytestmark=pytest.mark.skipif(os.getenv('DOVIDEO_AGENT_PG_TEST')!='1',reason='requires isolated migrated PostgreSQL')


@pytest.fixture
def fixture():
    settings=Settings.from_env();require_test_storage(settings)
    engine=create_engine(settings.database_url)
    with Session(engine) as s:
        user=User(id=uuid.uuid4(),username='eng_'+uuid.uuid4().hex[:24],password_hash='fixture',nickname='fixture')
        s.add(user);s.flush()
        course=Course(id=uuid.uuid4(),created_by=user.id,name='isolated recovery')
        s.add(course);s.flush()
        thread=AgentThread(id=uuid.uuid4(),user_id=user.id,course_id=course.id)
        s.add(thread);s.flush()
        run=AgentRun(id=uuid.uuid4(),thread_id=thread.id,input_text='解释定义',state='QUEUED',checkpoint={},usage={})
        s.add(run);s.commit()
        ids=SimpleNamespace(run=run.id,user=user.id,course=course.id)
    yield engine,ids
    engine.dispose()


def test_claim_exhaustion_deadline_and_fencing(fixture):
    engine,ids=fixture
    with Session(engine) as s:
        row=claim(s);token=row.lease_token;s.commit()
        assert row.claim_attempts==1
        row.lease_until=datetime.now(timezone.utc)-timedelta(seconds=1);s.commit()
        row=claim(s);s.commit()
        assert row.claim_attempts==2 and row.lease_token!=token
        row.claim_attempts=row.max_claim_attempts
        row.lease_until=datetime.now(timezone.utc)-timedelta(seconds=1);s.commit()
        assert claim(s) is None;s.commit()
        row=s.get(AgentRun,ids.run)
        assert row.state=='FAILED' and row.error_code=='LEASE_EXHAUSTED'
        assert len(s.scalars(select(AgentEvent).where(AgentEvent.run_id==ids.run,AgentEvent.kind=='run.failed')).all())==1


def test_worker_recovers_tools_without_duplicate_practice(fixture):
    engine,ids=fixture
    ref={'source_id':'S1','resource_id':str(uuid.uuid4()),'content':'定义'}
    arguments={'question':'定义是什么','expected_answer':'定义','source_ids':['S1'],'rubric':[]}
    call_id='frozen-tool-call'
    with Session(engine) as s:
        run=claim(s);s.commit()
        context={'storage':SimpleNamespace(engine=engine),'run_id':run.id,'lease_token':run.lease_token,
                 'references':{'S1':ref},'tool_call_id':call_id}
        first=execute('create_practice_question',arguments,['create_practice_question'],context)
        run=s.get(AgentRun,run.id);run.lease_until=datetime.now(timezone.utc)-timedelta(seconds=1);s.commit()
        run=claim(s);s.commit();context['lease_token']=run.lease_token
        second=execute('create_practice_question',arguments,['create_practice_question'],context)
        assert first==second
        assert len(s.scalars(select(PracticeQuestion).where(PracticeQuestion.run_id==ids.run)).all())==1
        context['lease_token']='stale'
        assert execute('create_practice_question',arguments,['create_practice_question'],context)['code']=='RUN_NOT_ACTIVE'
        run.state='FAILED';s.commit()


def test_worker_terminal_stream_failure_is_durable_and_private(fixture):
    engine,ids=fixture
    from dovideo.agents.reliability import AgentFailure
    class Broken:
        def stream(self,messages,tools,output,check):
            output('部分正文')
            raise AgentFailure('PARTIAL_STREAM')
    with patch.dict(os.environ,{'DOVIDEO_CHAT_STREAM':'1'}):
        assert run_once(SimpleNamespace(engine=engine),Broken())
    with Session(engine) as s:
        row=s.get(AgentRun,ids.run)
        assert row.state=='FAILED' and row.error_code=='PARTIAL_STREAM' and row.answer=='部分正文'
        assert len(s.scalars(select(AgentEvent).where(AgentEvent.run_id==ids.run,AgentEvent.kind=='model.delta')).all())==1


def test_worker_future_checkpoint_and_previous_delta_are_not_replayed(fixture):
    engine,ids=fixture
    with Session(engine) as s:
        row=s.get(AgentRun,ids.run)
        row.checkpoint={'schema_version':99,'messages':[]};s.commit()
    assert run_once(SimpleNamespace(engine=engine),object())
    with Session(engine) as s:
        row=s.get(AgentRun,ids.run)
        assert row.error_code=='CHECKPOINT_INCOMPATIBLE'
        row.state='RUNNING';row.lease_until=datetime.now(timezone.utc)-timedelta(seconds=1)
        row.checkpoint={'schema_version':1,'config_fingerprint':fingerprint(),'messages':[]}
        s.add(AgentEvent(run_id=ids.run,kind='model.delta',data={'text':'已经展示'}));s.commit()
    assert run_once(SimpleNamespace(engine=engine),object())
    with Session(engine) as s:
        assert s.get(AgentRun,ids.run).error_code=='PARTIAL_STREAM'


def test_admission_quotas_are_enforced_in_shared_database(fixture):
    engine,ids=fixture
    from dovideo.agents.service import run
    from dovideo.errors import ApiError
    with Session(engine) as s:
        old=s.get(AgentRun,ids.run)
        thread=AgentThread(id=uuid.uuid4(),user_id=ids.user,course_id=ids.course)
        s.add(thread);s.flush()
        with patch.dict(os.environ,{'DOVIDEO_MAX_USER_RUNS':'1'}):
            with pytest.raises(ApiError) as exc:
                run(s,SimpleNamespace(id=ids.user),thread.id,'another run')
        assert exc.value.code=='RUN_CAPACITY_EXCEEDED'
        old.state='FAILED';s.commit()


def test_public_sse_hides_private_observation_and_cross_user_access(fixture):
    engine,ids=fixture
    from fastapi.testclient import TestClient
    from app.gateway import create_app
    from dovideo.dependencies import current_user,get_session
    from contextlib import contextmanager
    class Storage:
        def ensure_bucket(self):pass
        def close(self):pass
    with Session(engine) as s:
        row=s.get(AgentRun,ids.run);row.state='FAILED'
        s.add_all([AgentEvent(run_id=ids.run,kind='private.model.attempt',data={'sentinel':'PRIVATE_METADATA'}),
                   AgentEvent(run_id=ids.run,kind='run.failed',data={'code':'PARTIAL_STREAM'})]);s.commit()
    app=create_app(object(),lambda _:Storage())
    def sessions():
        with Session(engine) as session:
            yield session
            session.commit()
    app.dependency_overrides[get_session]=sessions
    app.dependency_overrides[current_user]=lambda:SimpleNamespace(id=ids.user)
    with TestClient(app) as client:
        response=client.get(f'/api/v2/runs/{ids.run}/events')
        assert response.status_code==200 and 'run.failed' in response.text
        assert 'PRIVATE_METADATA' not in response.text and 'private.model' not in response.text
        app.dependency_overrides[current_user]=lambda:SimpleNamespace(id=uuid.uuid4())
        assert client.get(f'/api/v2/runs/{ids.run}').status_code==404
        assert client.get(f'/api/v2/runs/{ids.run}/events').status_code==404
