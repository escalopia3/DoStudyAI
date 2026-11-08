import copy
import unittest
import uuid
from types import SimpleNamespace as Obj
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from dovideo.models import Base,User,Resource,ResourceVersion,ProcessingJob
from dovideo.business.reparse import enqueue_refresh,publish_refresh,retained_artifact_keys
from dovideo.errors import ApiError

@compiles(JSONB,'sqlite')
def jsonb_sqlite(type_,compiler,**kwargs):return 'JSON'


class ReparseTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine,tables=[User.__table__,Resource.__table__,ResourceVersion.__table__,ProcessingJob.__table__])
        self.s=Session(self.engine)
        self.user=User(id=uuid.uuid4(),username='owner',password_hash='fixture',nickname='owner')
        self.resource=Resource(id=uuid.uuid4(),owner_id=self.user.id,kind='PPTX',display_name='test.pptx')
        self.version=ResourceVersion(id=uuid.uuid4(),resource_id=self.resource.id,version_no=1,
            object_key='source-key',content_type='application/vnd.openxmlformats-officedocument.presentationml.presentation',
            size_bytes=3,checksum_sha256='a'*64,state='PARSED')
        self.resource.current_version_id=self.version.id
        self.parsed=ProcessingJob(id=uuid.uuid4(),kind='PROCESS_RESOURCE',idempotency_key='original',
            resource_version_id=self.version.id,state='SUCCEEDED',payload={'artifacts':{
                'document.json':{'key':'original-document','version_id':'old','sha256':'b'*64}}})
        self.s.add_all([self.user,self.resource,self.version,self.parsed]);self.s.flush()

    def tearDown(self):self.s.close();self.engine.dispose()

    def refresh(self):
        return ProcessingJob(id=uuid.uuid4(),kind='REFRESH_RESOURCE',idempotency_key='refresh',resource_version_id=self.version.id,
            state='SUCCEEDED',payload={'canonical_parse_job_id':str(self.parsed.id),'expected_source_sha256':'a'*64,
            'formula_review_sha256':'c'*64,'expected_document_sha256':'b'*64})

    def test_enqueue_checks_owner_and_busy_scope(self):
        with self.assertRaises(ApiError):enqueue_refresh(self.s,Obj(id=uuid.uuid4()),self.resource.id,'c'*64)
        with patch('dovideo.business.reparse.jobs.enqueue',return_value=Obj(id='queued')) as enqueue:
            result=enqueue_refresh(self.s,self.user,self.resource.id,'c'*64)
            self.assertEqual('queued',result.id)
            payload=enqueue.call_args.args[-1]
            self.assertEqual('b'*64,payload['expected_document_sha256'])
            self.assertEqual('c'*64,payload['formula_review_sha256'])
        busy=self.refresh();busy.state='RUNNING';self.s.add(busy);self.s.flush()
        with self.assertRaises(ApiError) as error:enqueue_refresh(self.s,self.user,self.resource.id,'c'*64)
        self.assertEqual('RESOURCE_BUSY',error.exception.code)

    def test_publication_retains_history_and_requires_fresh_index(self):
        refresh=self.refresh();self.s.add(refresh);self.s.flush()
        new={'document.json':{'key':'new-document','version_id':'new','sha256':'d'*64}}
        with patch('dovideo.knowledge.enqueue_index',return_value=Obj(id='new-index-job')) as enqueue:
            publish_refresh(self.s,refresh,new)
        self.assertEqual(new,self.parsed.payload['artifacts'])
        self.assertEqual({'original-document','new-document'},retained_artifact_keys(self.parsed.payload))
        self.assertTrue(enqueue.call_args.kwargs['rebuild'])
        self.assertEqual('new-index-job',refresh.payload['index_job_id'])
        self.assertEqual(new,refresh.payload['artifacts'])

    def test_stale_source_or_parse_snapshot_cannot_replace_current_artifacts(self):
        for stale in ('source','parse'):
            with self.subTest(stale=stale):
                refresh=self.refresh()
                refresh.payload=dict(refresh.payload,**({'expected_source_sha256':'x'*64} if stale=='source'
                    else {'expected_document_sha256':'x'*64}))
                original=copy.deepcopy(self.parsed.payload)
                with patch('dovideo.knowledge.enqueue_index') as enqueue:publish_refresh(self.s,refresh,{})
                self.assertEqual('FAILED',refresh.state)
                self.assertEqual('PARSED_SNAPSHOT_CHANGED',refresh.error_code)
                self.assertEqual(original,self.parsed.payload)
                enqueue.assert_not_called()


if __name__=='__main__':unittest.main()
