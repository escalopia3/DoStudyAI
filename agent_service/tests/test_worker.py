import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from agent_service.config import Settings
from agent_service.contracts import ParseRequest
from agent_service.store import Store, metadata, events, jobs
from agent_service.worker import Worker
from sqlalchemy import select
from sqlalchemy import update
from knowledge_service.indexing.store import IndexStore, metadata as index_metadata


class Objects:
    def __init__(self): self.uploads={}
    def fput_object(self,bucket,key,path): self.uploads[key]=Path(path).read_bytes()
    def fget_object(self,bucket,key,path): Path(path).write_bytes(self.uploads[key])


class FakeEmbeddings:
    version="fake-d3-parent-child-v1"
    dimension=3
    def embed_documents(self,texts): return [[1.0,0.0,0.0] for _ in texts]
    def embed_query(self,text): return [1.0,0.0,0.0]


class FakeQdrant:
    def __init__(self): self.points=[]
    def ensure_schema(self): pass
    def upsert(self,owner_id,resource_id,source_revision,index_revision,embedding_version,chunks,vectors):
        self.points=[{"payload":c.to_dict() | {"resourceId":resource_id,
            "indexRevision":index_revision}} for c in chunks]
    def count(self,resource_id,index_revision): return len(self.points)
    def sample(self,resource_id,index_revision,limit=10): return self.points[:limit]
    def manifest_hash(self,chunks): return "manifest"
    def close(self): pass


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.store=Store('sqlite:///'+str(self.root/'db.sqlite'))
        metadata.create_all(self.store.engine)
        self.request=ParseRequest(jobId='worker-job-01',resourceId='1',userId='2',courseId='3',sourceRevision='rev1',sourceType='VIDEO')
        self.store.submit(self.request)
        self.worker=Worker.__new__(Worker)
        self.worker.settings=Settings('unused','x'*32,work_dir=self.root/'work',timeout=15)
        self.worker.store=self.store;self.worker.stopping=False
        self.worker.storage_error_types=()
        self.worker.objects=Objects();self.worker.bucket='media'
        index_store=IndexStore('sqlite:///'+str(self.root/'db.sqlite'))
        index_metadata.create_all(index_store.engine)
        self.worker._index_components=(index_store,FakeQdrant(),FakeEmbeddings())
        self.worker.source=lambda request: request | {'videoContext':{'source':'video','segments':[
            {'startMs':0,'endMs':1000,'transcript':'hello','ocrTexts':[],'evidenceFrames':[]}]}}
    def tearDown(self):
        self.worker._index_components[0].engine.dispose()
        self.store.engine.dispose();self.temp.cleanup()
    def test_real_video_subprocess_publishes_three_artifacts(self):
        self.assertTrue(self.worker.run_once())
        result=self.store.get(self.request.jobId)
        self.assertEqual(result['state'],'PARSED',result)
        self.assertEqual(len(self.worker.objects.uploads),3)
        self.assertEqual(list((self.root/'work').iterdir()),[])

    def test_parsed_artifact_is_indexed_and_becomes_ready(self):
        self.assertTrue(self.worker.run_once())
        with self.store.engine.begin() as db:
            db.execute(update(jobs).values(available_at=0))
        self.assertTrue(self.worker.index_once())
        result=self.store.get(self.request.jobId)
        self.assertEqual(result['state'],'READY',result)
        active=self.worker._index_components[0].active(['1'])
        self.assertEqual(len(active),1)
        self.assertEqual(active[0]['source_revision'],'rev1')
    def test_revoked_source_never_publishes(self):
        def denied(_): raise ValueError('SOURCE_CHANGED')
        self.worker.source=denied
        self.worker.run_once()
        self.assertEqual(self.store.get(self.request.jobId)['state'],'FAILED')
        self.assertFalse(self.worker.objects.uploads)
    def test_cancel_before_worker_prevents_work(self):
        self.store.cancel(self.request.jobId)
        self.assertFalse(self.worker.run_once())
        self.assertFalse(self.worker.objects.uploads)
    def test_callback_failure_is_durable_and_delayed(self):
        self.worker.http=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(503)),base_url='http://java')
        self.worker.callback_once()
        with self.store.engine.connect() as db:
            row=db.execute(select(events)).mappings().first()
            self.assertEqual(row['delivered'],0);self.assertEqual(row['attempts'],1)
        self.worker.http.close()
    def test_parser_killed_before_temp_cleanup(self):
        self.worker.settings=Settings('unused','x'*32,work_dir=self.root/'work',timeout=0)
        class Process:
            returncode=None
            killed=False
            def poll(self): return self.returncode
            def kill(self): self.killed=True;self.returncode=-1
            def wait(self,timeout): return self.returncode
        proc=Process()
        with patch('agent_service.worker.subprocess.Popen',return_value=proc): self.worker.run_once()
        self.assertTrue(proc.killed)
        self.assertEqual(list((self.root/'work').iterdir()),[])
        self.assertEqual(self.store.get(self.request.jobId)['state'],'FAILED')


if __name__=='__main__': unittest.main()
