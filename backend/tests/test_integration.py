"""Opt-in real storage tests, restricted to explicitly isolated test storage."""
import hashlib
import io
import os
import uuid
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.gateway import create_app
from app.worker import run_once
from dovideo.config import Settings
from dovideo.storage import Storage
from dovideo.db import session_scope
from dovideo.models import ProcessingJob, ResourceVersion, UploadSession
from dovideo.business import jobs

@unittest.skipUnless(os.getenv('DOVIDEO_INTEGRATION') == '1', 'requires isolated v2 services')
class IntegrationTests(unittest.TestCase):
    def test_index_failure_publication_fence_and_cleanup(self):
        from dovideo.models import Resource, KnowledgeIndex, ActiveKnowledgeIndex
        from dovideo.knowledge import index_config, collection_name, prepare, publish, build, scope_filter
        from dovideo.validation import InvalidResource
        from qdrant_client import models as qm
        with TestClient(create_app(self.settings)) as client:
            auth = self.account(client)
            course = client.post('/api/v2/courses',headers=auth,json={'name':'Index isolation'}).json()['id']
            with session_scope(self.storage.engine) as session:
                from dovideo.models import Course
                owner = session.get(Course,uuid.UUID(course)).created_by
                resource = Resource(id=uuid.uuid4(),owner_id=owner,kind='PDF',display_name='test')
                session.add(resource)
                session.flush()
                version = ResourceVersion(id=uuid.uuid4(),resource_id=resource.id,version_no=1,
                    object_key='tests/'+uuid.uuid4().hex,content_type='application/pdf',size_bytes=1,state='PARSED')
                session.add(version)
                session.flush()
                resource.current_version_id=version.id
                config=index_config()
                job=jobs.enqueue(session,'INDEX_RESOURCE','test-index:'+uuid.uuid4().hex,version.id,
                    {'resource_id':str(resource.id),'owner_id':str(owner),'config':config,
                     'collection':collection_name(config),'expected_previous':None})
                job_id,version_id,resource_id=job.id,version.id,resource.id
            # A hash mismatch must fail before touching the embedding model.
            raw=b'{}'
            key='tests/'+uuid.uuid4().hex
            obj=self.storage.minio.put_object(self.storage.bucket,key,io.BytesIO(raw),len(raw))
            with self.assertRaisesRegex(InvalidResource,'HASH'):
                build(self.storage,{'artifact':{'key':key,'version_id':obj.version_id,'sha256':'0'*64}})
            self.storage.minio.remove_object(self.storage.bucket,key,version_id=obj.version_id)
            with session_scope(self.storage.engine) as session:
                job=jobs.claim(session,'test',('INDEX_RESOURCE',),target_id=job_id)
                token=job.lease_token
                prepare(session,job,token)
            with session_scope(self.storage.engine) as session:
                self.assertFalse(jobs.complete(session,job_id,str(uuid.uuid4())))
                self.assertIsNone(session.get(ActiveKnowledgeIndex,resource_id))
                job=session.get(ProcessingJob,job_id)
                job.cancel_requested=True
            with session_scope(self.storage.engine) as session:
                self.assertFalse(jobs.complete(session,job_id,token))
                jobs.fail(session,job_id,token,'CANCELLED')
                self.assertEqual(session.get(ResourceVersion,version_id).state,'PARSED')
            # Valid lease alone is insufficient if source deletion committed.
            with session_scope(self.storage.engine) as session:
                job=session.get(ProcessingJob,job_id)
                job.cancel_requested=False
                job.state='QUEUED'
                job=jobs.claim(session,'test',('INDEX_RESOURCE',),target_id=job_id)
                token=job.lease_token
                prepare(session,job,token)
                session.get(Resource,resource_id).deleted_at=datetime.now(timezone.utc)
            with session_scope(self.storage.engine) as session:
                job=session.get(ProcessingJob,job_id)
                self.assertTrue(jobs.complete(session,job_id,token))
                publish(session,job,token,{'manifest':{},'artifact':{}})
                self.assertEqual(job.state,'FAILED')
                self.assertIsNone(session.get(ActiveKnowledgeIndex,resource_id))
            # Reclaim orphan vectors using real Qdrant, not mocked cleanup.
            from dovideo.knowledge import ensure_collection
            collection=collection_name(config)
            ensure_collection(self.storage.qdrant,collection,1024)
            self.storage.qdrant.upsert(collection,[qm.PointStruct(id=str(uuid.uuid4()),
                vector={'dense':[1.0]+[0.0]*1023},
                payload={'resourceId':str(resource_id),'indexRevision':token})],wait=True)
            with session_scope(self.storage.engine) as session:
                for index in session.scalars(select(KnowledgeIndex).where(KnowledgeIndex.resource_id==resource_id)):
                    index.created_at=datetime.now(timezone.utc)-timedelta(days=2)
            from dovideo.maintenance import sweep
            sweep(self.storage)
            self.assertEqual(self.storage.qdrant.count(collection,
                count_filter=scope_filter(resource_id=resource_id),exact=True).count,0)

    def test_real_docx_worker_artifacts(self):
        from docx import Document
        with TestClient(create_app(self.settings)) as client:
            auth = self.account(client)
            other = self.account(client)
            course = client.post('/api/v2/courses', headers=auth, json={'name':'Parsing E2E'}).json()['id']
            stream = io.BytesIO()
            document = Document()
            document.add_heading('Transport protocols', 0)
            document.add_paragraph('TCP provides reliable communication.')
            document.save(stream)
            data=stream.getvalue()
            mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            upload=client.post(f'/api/v2/courses/{course}/resources/uploads',
                headers=dict(auth, **{'Idempotency-Key':uuid.uuid4().hex}),
                json={'filename':'lecture.docx','contentType':mime,'sizeBytes':len(data)}).json()
            with session_scope(self.storage.engine) as session:
                key=session.get(UploadSession,uuid.UUID(upload['uploadId'])).object_key
            self.storage.minio.put_object(self.storage.bucket,key,io.BytesIO(data),len(data),content_type=mime)
            receipt=client.post('/api/v2/uploads/'+upload['uploadId']+'/complete',headers=auth).json()
            run_once(self.storage,timeout=90,target_id=uuid.UUID(receipt['jobId']))
            with session_scope(self.storage.engine) as session:
                job=session.scalar(select(ProcessingJob).where(ProcessingJob.idempotency_key=='process:'+receipt['versionId']))
                parse_id=job.id
            run_once(self.storage,timeout=120,target_id=parse_id)
            with session_scope(self.storage.engine) as session:
                job=session.get(ProcessingJob,parse_id)
                self.assertEqual(job.state,'SUCCEEDED',job.error_code)
                self.assertEqual(session.get(ResourceVersion,uuid.UUID(receipt['versionId'])).state,'PARSED')
                item=job.payload['artifacts']['content.md']
            response=self.storage.minio.get_object(self.storage.bucket,item['key'],version_id=item['version_id'])
            try:
                content=response.read()
            finally:
                response.close()
                response.release_conn()
            self.assertIn(b'TCP',content)
            self.assertEqual(hashlib.sha256(content).hexdigest(),item['sha256'])
            path='/api/v2/resources/'+receipt['resourceId']+'/artifacts/document.json'
            self.assertEqual(client.get(path,headers=auth).status_code,200)
            self.assertEqual(client.get(path,headers=other).status_code,404)
            # Block 5: actual offline BGE-M3 + Qdrant + authorized evidence.
            with session_scope(self.storage.engine) as session:
                index_job = session.scalar(select(ProcessingJob).where(
                    ProcessingJob.resource_version_id == uuid.UUID(receipt['versionId']),
                    ProcessingJob.kind == 'INDEX_RESOURCE'))
                index_job_id = index_job.id
            run_once(self.storage, timeout=300, target_id=index_job_id)
            with session_scope(self.storage.engine) as session:
                job = session.get(ProcessingJob,index_job_id)
                self.assertEqual(job.state,'SUCCEEDED',job.error_code)
                self.assertEqual(session.get(ResourceVersion,uuid.UUID(receipt['versionId'])).state,'PARSED')
            search_path = f'/api/v2/courses/{course}/knowledge/search'
            result = client.post(search_path, headers=auth, json={'question':'What does TCP provide?'} )
            self.assertEqual(result.status_code,200,result.text)
            evidence = result.json()['evidence']
            self.assertTrue(evidence)
            self.assertEqual(evidence[0]['resourceId'],receipt['resourceId'])
            self.assertIn('TCP',evidence[0]['content'])
            self.assertTrue(evidence[0]['locators'])
            query_path=f'/api/v2/courses/{course}/knowledge/query'
            overview=client.post(query_path,headers=auth,json={'intent':'overview'} )
            self.assertEqual(overview.status_code,200,overview.text)
            self.assertTrue(overview.json()['coverage']['complete'])
            self.assertTrue(overview.json()['outline'])
            self.assertIn('TCP',' '.join(e['content'] for e in overview.json()['evidence']))
            self.assertEqual(client.post(query_path,headers=other,json={'intent':'overview'}).status_code,404)
            self.assertEqual(client.post(query_path,headers=auth,json={'intent':'overview','cursor':'invalid'}).status_code,409)
            detail=client.post(query_path,headers=auth,json={'intent':'detail','query':'TCP'})
            self.assertEqual(detail.status_code,200,detail.text)
            self.assertTrue(detail.json()['evidence'])
            previous = evidence[0]['indexRevision']
            self.assertEqual(client.post(search_path,headers=other,json={'question':'TCP'}).status_code,404)
            self.assertEqual(client.post(search_path,headers=auth,json={'question':'   '}).status_code,422)
            rebuild_path = '/api/v2/resources/'+receipt['resourceId']+'/indexes'
            self.assertEqual(client.post(rebuild_path,headers=other).status_code,404)
            rebuild = client.post(rebuild_path,headers=auth).json()
            again = client.post(rebuild_path,headers=auth).json()
            self.assertEqual(rebuild['jobId'],again['jobId'])
            self.assertEqual(client.post(search_path,headers=auth,json={'question':'TCP'}).json()['evidence'][0]['indexRevision'],previous)
            # Cancelled rebuild must leave the published index available.
            self.assertEqual(client.post('/api/v2/jobs/'+rebuild['jobId']+'/cancel',headers=auth).status_code,200)
            self.assertEqual(client.post(search_path,headers=auth,json={'question':'TCP'}).json()['evidence'][0]['indexRevision'],previous)
            retry = client.post('/api/v2/jobs/'+rebuild['jobId']+'/retry',headers=auth)
            self.assertEqual(retry.status_code,200,retry.text)
            run_once(self.storage, timeout=300, target_id=uuid.UUID(rebuild['jobId']))
            replacement = client.post(search_path,headers=auth,json={'question':'TCP'}).json()['evidence'][0]['indexRevision']
            self.assertNotEqual(previous,replacement)
            status = client.get(f'/api/v2/courses/{course}/knowledge',headers=auth).json()['items'][0]
            self.assertEqual(status['activeIndexId'],replacement)
            self.assertEqual(status['parseState'],'PARSED')
            empty_course=client.post('/api/v2/courses',headers=auth,json={'name':'Other course'}).json()['id']
            self.assertEqual(client.post(f'/api/v2/courses/{empty_course}/knowledge/search',
                headers=auth,json={'question':'TCP'}).json()['evidence'],[])
            self.assertEqual(client.post(search_path,json={'question':'TCP'}).status_code,401)
            # Exercise the actual CLI, retaining a reproducible smoke report.
            import subprocess
            import sys
            import json
            from pathlib import Path
            from dovideo.config import PROJECT_ROOT
            from dovideo.models import Resource
            with session_scope(self.storage.engine) as session:
                owner=session.get(Resource,uuid.UUID(receipt['resourceId'])).owner_id
            dataset=PROJECT_ROOT/'tmp/block5-questions.json'
            output=PROJECT_ROOT/'tmp/block5-evaluation.json'
            dataset.write_text(json.dumps([{'question':q,'expectedResourceIds':[receipt['resourceId']]}
                for q in ['What does TCP provide?','TCP提供什么保证？','可靠通信使用什么协议？']],ensure_ascii=False),encoding='utf-8')
            subprocess.run([sys.executable,'-m','dovideo.evaluate','--user-id',str(owner),
                '--course-id',course,'--dataset',str(dataset),'--output',str(output)],check=True,timeout=120)
            report=json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(report['count'],3)
            self.assertEqual(report['recallAtK'],1)
            # Corrupt only the new build input. Published evidence must survive.
            failed=client.post(rebuild_path,headers=auth).json()
            with session_scope(self.storage.engine) as session:
                job=session.get(ProcessingJob,uuid.UUID(failed['jobId']))
                job.payload=dict(job.payload,artifact=dict(job.payload['artifact'],sha256='0'*64))
            run_once(self.storage,timeout=60,target_id=uuid.UUID(failed['jobId']))
            job_status=client.get('/api/v2/jobs/'+failed['jobId'],headers=auth).json()
            self.assertEqual(job_status['state'],'FAILED')
            self.assertEqual(job_status['errorCode'],'DOCUMENT_HASH_OR_SIZE_MISMATCH')
            self.assertEqual(client.post(search_path,headers=auth,json={'question':'TCP'}).json()['evidence'][0]['indexRevision'],replacement)
            self.assertEqual(client.delete('/api/v2/resources/'+receipt['resourceId'],headers=auth).status_code,202)
            self.assertEqual(client.post(search_path,headers=auth,json={'question':'TCP'}).json()['evidence'],[])
            with session_scope(self.storage.engine) as session:
                cleanup=session.scalar(select(ProcessingJob).where(ProcessingJob.kind=='DELETE_RESOURCE',
                    ProcessingJob.resource_version_id==uuid.UUID(receipt['versionId'])))
                cleanup.available_at=datetime.now(timezone.utc)
                cleanup_id=cleanup.id
            run_once(self.storage,timeout=60,target_id=cleanup_id)
            with session_scope(self.storage.engine) as session:
                cleanup=session.get(ProcessingJob,cleanup_id)
                self.assertEqual(cleanup.state,'SUCCEEDED',cleanup.error_code)

    @classmethod
    def setUpClass(cls):
        cls.settings = Settings.from_env()
        from dovideo.test_isolation import require_test_storage
        require_test_storage(cls.settings)
        cls.storage = Storage(cls.settings)
        cls.storage.ensure_bucket()

    @classmethod
    def tearDownClass(cls):
        cls.storage.close()

    def account(self, client):
        name = 't_' + uuid.uuid4().hex[:24]
        data = {'username': name, 'password': 'Test-password-123'}
        self.assertEqual(client.post('/api/v2/auth/register', json=data).status_code, 201)
        response = client.post('/api/v2/auth/login', json=data)
        self.assertEqual(response.status_code, 200)
        return {'Authorization': 'Bearer ' + response.json()['token']}

    def test_upload_immutable_and_authorized(self):
        with TestClient(create_app(self.settings)) as client:
            auth = self.account(client)
            other = self.account(client)
            course = client.post('/api/v2/courses', headers=auth, json={'name':'test'}).json()['id']
            self.assertEqual(client.get('/api/v2/courses/' + course, headers=other).status_code, 404)
            self.assertEqual(client.put('/api/v2/courses/' + course + '/members', headers=auth, json={}).status_code, 404)
            data = b'%PDF-1.7\nverified content\n%%EOF'
            headers = dict(auth, **{'Idempotency-Key': uuid.uuid4().hex})
            body = {'filename':'lecture.pdf','contentType':'application/pdf','sizeBytes':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
            path = '/api/v2/courses/' + course + '/resources/uploads'
            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(lambda _: client.post(path, headers=headers, json=body), range(2)))
            self.assertTrue(all(r.status_code == 201 for r in responses))
            upload_id = responses[0].json()['uploadId']
            self.assertEqual(upload_id, responses[1].json()['uploadId'])
            with session_scope(self.storage.engine) as session:
                upload = session.get(UploadSession, uuid.UUID(upload_id))
                key = upload.object_key
            self.storage.minio.put_object(self.storage.bucket, key, io.BytesIO(data), len(data), content_type='application/pdf')
            response = client.post(f'/api/v2/uploads/{upload_id}/complete', headers=auth)
            self.assertEqual(response.status_code, 202, response.text)
            receipt = response.json()
            again = client.post(f'/api/v2/uploads/{upload_id}/complete', headers=auth).json()
            self.assertEqual(receipt, again)
            replacement = b'evil replacement'
            self.storage.minio.put_object(self.storage.bucket, key, io.BytesIO(replacement), len(replacement), content_type='application/pdf')
            for _ in range(20):
                run_once(self.storage, timeout=30, target_id=uuid.UUID(receipt['jobId']))
                with session_scope(self.storage.engine) as session:
                    job = session.get(ProcessingJob, uuid.UUID(receipt['jobId']))
                    if job.state in ('SUCCEEDED','FAILED'):
                        self.assertEqual(job.state, 'SUCCEEDED', job.error_code)
                        break
            with session_scope(self.storage.engine) as session:
                version = session.get(ResourceVersion, uuid.UUID(receipt['versionId']))
                self.assertEqual(version.checksum_sha256, hashlib.sha256(data).hexdigest())
                self.assertTrue(version.object_key.startswith('resources/'))
            resource = receipt['resourceId']
            self.assertEqual(client.get(f'/api/v2/resources/{resource}/download', headers=other).status_code,404)
            self.assertEqual(client.get(f'/api/v2/resources/{resource}/download', headers=auth).status_code,200)
            self.assertEqual(client.delete(f'/api/v2/resources/{resource}', headers=auth).status_code,202)
            self.assertEqual(client.get(f'/api/v2/resources/{resource}/download', headers=auth).status_code,404)
            with session_scope(self.storage.engine) as session:
                cleanup = session.scalar(select(ProcessingJob).where(ProcessingJob.idempotency_key == 'delete:' + receipt['versionId']))
                cleanup.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                cleanup_id = cleanup.id
            for _ in range(20):
                run_once(self.storage, timeout=30, target_id=cleanup_id)
                with session_scope(self.storage.engine) as session:
                    cleanup = session.get(ProcessingJob, cleanup_id)
                    if cleanup.state in ('SUCCEEDED','FAILED'):
                        self.assertEqual(cleanup.state, 'SUCCEEDED', cleanup.error_code)
                        break
            with session_scope(self.storage.engine) as session:
                self.assertEqual(session.get(ResourceVersion, uuid.UUID(receipt['versionId'])).state, 'DELETED')

    def test_lease_fencing_and_exhaustion(self):
        kind = 'TEST_' + uuid.uuid4().hex[:16]
        with session_scope(self.storage.engine) as session:
            job = jobs.enqueue(session, kind, uuid.uuid4().hex)
            job_id = job.id
        with session_scope(self.storage.engine) as session:
            first = jobs.claim(session, 'worker', (kind,))
            token = first.lease_token
            first.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        with session_scope(self.storage.engine) as session:
            second = jobs.claim(session, 'worker', (kind,))
            self.assertNotEqual(token, second.lease_token)
            session.flush()
            self.assertFalse(jobs.complete(session, job_id, token))
            second.attempts = second.max_attempts
            second.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        with session_scope(self.storage.engine) as session:
            self.assertIsNone(jobs.claim(session, 'worker', (kind,)))
        with session_scope(self.storage.engine) as session:
            self.assertEqual(session.get(ProcessingJob, job_id).state, 'FAILED')

    def test_parts_resume_and_cancel(self):
        from dovideo.business.resources import PART_SIZE
        with TestClient(create_app(self.settings)) as client:
            auth = self.account(client)
            course = client.post('/api/v2/courses', headers=auth, json={'name':'parts'}).json()['id']
            data = b'%PDF-1.7\n' + b'x' * PART_SIZE
            response = client.post(f'/api/v2/courses/{course}/resources/uploads',
                headers=dict(auth, **{'Idempotency-Key':uuid.uuid4().hex}),
                json={'filename':'large.pdf','contentType':'application/pdf','sizeBytes':len(data)})
            self.assertEqual(response.status_code, 201, response.text)
            upload_id = response.json()['uploadId']
            self.assertEqual(response.json()['mode'], 'parts')
            with session_scope(self.storage.engine) as session:
                key = session.get(UploadSession, uuid.UUID(upload_id)).object_key
            for number, block in enumerate([data[:PART_SIZE], data[PART_SIZE:]], 1):
                signed = client.post(f'/api/v2/uploads/{upload_id}/parts/{number}', headers=auth)
                self.assertEqual(signed.status_code, 200)
                self.storage.minio.put_object(self.storage.bucket, f'{key}.parts/{number}', io.BytesIO(block), len(block))
            parts = client.get(f'/api/v2/uploads/{upload_id}/parts', headers=auth)
            self.assertEqual(len(parts.json()['parts']), 2)
            completed = client.post(f'/api/v2/uploads/{upload_id}/complete', headers=auth)
            self.assertEqual(completed.status_code, 202, completed.text)
            receipt = completed.json()
            cancelled = client.post('/api/v2/jobs/' + receipt['jobId'] + '/cancel', headers=auth)
            self.assertEqual(cancelled.json()['state'], 'CANCELLED')
            with session_scope(self.storage.engine) as session:
                version = session.get(ResourceVersion, uuid.UUID(receipt['versionId']))
                self.assertEqual(version.state, 'CANCELLED')
            retried = client.post('/api/v2/jobs/' + receipt['jobId'] + '/retry', headers=auth)
            self.assertEqual(retried.json()['state'], 'QUEUED')

    def test_running_cancel_and_concurrent_login(self):
        kind = 'TEST_' + uuid.uuid4().hex[:16]
        with session_scope(self.storage.engine) as session:
            job = jobs.enqueue(session, kind, uuid.uuid4().hex)
            job_id = job.id
        with session_scope(self.storage.engine) as session:
            job = jobs.claim(session, 'test', (kind,))
            token = job.lease_token
            job.cancel_requested = True
        with session_scope(self.storage.engine) as session:
            self.assertFalse(jobs.complete(session, job_id, token))
            self.assertFalse(jobs.heartbeat(session, job_id, token))
            jobs.fail(session, job_id, token, 'CANCELLED')
        with session_scope(self.storage.engine) as session:
            self.assertEqual(session.get(ProcessingJob, job_id).state, 'CANCELLED')
        with TestClient(create_app(self.settings)) as client:
            name = 'unknown_' + uuid.uuid4().hex[:16]
            with ThreadPoolExecutor(max_workers=4) as pool:
                responses = list(pool.map(lambda _: client.post('/api/v2/auth/login',
                    json={'username':name,'password':'incorrect'}), range(4)))
            self.assertEqual([r.status_code for r in responses], [401]*4)
