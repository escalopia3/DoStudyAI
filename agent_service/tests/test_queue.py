import tempfile
import unittest
from pathlib import Path
from sqlalchemy import update, select
from fastapi.testclient import TestClient
from agent_service.store import Store, metadata, jobs, events, Conflict
from agent_service.contracts import ParseRequest
from agent_service.config import Settings
from agent_service.api import create_app


def request(**kwargs):
    return ParseRequest(**(dict(jobId="job-00000001", resourceId="1", userId="2", courseId="3",
        sourceRevision="rev1", sourceType="PDF") | kwargs))


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.url = "sqlite:///" + str(Path(self.temp.name) / "test.db")
        self.store = Store(self.url)
        metadata.create_all(self.store.engine)
    def tearDown(self):
        self.store.engine.dispose()
        self.temp.cleanup()
    def test_idempotency_and_conflict(self):
        self.store.submit(request())
        self.store.submit(request())
        with self.assertRaises(Conflict): self.store.submit(request(sourceRevision="other"))
        with self.store.engine.connect() as db:
            self.assertEqual(len(db.execute(select(events)).all()), 1)
    def test_only_one_worker_claims(self):
        self.store.submit(request())
        self.assertIsNotNone(self.store.claim())
        self.assertIsNone(self.store.claim())
    def test_expired_attempt_cannot_publish(self):
        self.store.submit(request())
        old = self.store.claim()
        with self.store.engine.begin() as db: db.execute(update(jobs).values(lease_until=0))
        new = self.store.claim()
        self.assertFalse(self.store.finish(old['id'],old['attempt'],'PARSED'))
        self.assertTrue(self.store.finish(new['id'],new['attempt'],'PARSED',artifact='prefix'))
    def test_expired_lease_cannot_renew(self):
        self.store.submit(request()); row=self.store.claim()
        with self.store.engine.begin() as db: db.execute(update(jobs).values(lease_until=0))
        self.assertFalse(self.store.renew(row['id'],row['attempt'],45))
    def test_cancel_fences_worker(self):
        self.store.submit(request()); row=self.store.claim()
        cancelled=self.store.cancel(row['id'])
        self.assertEqual(cancelled['state'],'CANCELLED')
        self.assertFalse(self.store.finish(row['id'],row['attempt'],'PARSED'))
        self.assertFalse(self.store.renew(row['id'],row['attempt'],45))
    def test_attempt_limit(self):
        self.store.submit(request()); self.store.claim(max_attempts=1)
        with self.store.engine.begin() as db: db.execute(update(jobs).values(lease_until=0))
        self.assertIsNone(self.store.claim(max_attempts=1))
        self.assertEqual(self.store.get(request().jobId)['state'],'FAILED')
    def test_retry_is_delayed(self):
        self.store.submit(request()); row=self.store.claim()
        self.store.finish(row['id'],row['attempt'],'FAILED',retry=True)
        self.assertIsNone(self.store.claim())
    def test_parsed_can_be_claimed_for_index_and_ready_is_terminal(self):
        self.store.submit(request()); row=self.store.claim()
        self.store.finish(row['id'],row['attempt'],'PARSED',artifact='prefix')
        with self.store.engine.begin() as db:
            db.execute(update(jobs).values(available_at=0))
        indexed = self.store.claim_index()
        self.assertEqual(indexed['state'],'INDEXING')
        self.assertTrue(self.store.finish(indexed['id'],indexed['attempt'],'READY'))
        self.assertEqual(self.store.cancel(row['id'])['state'],'READY')
        self.assertIsNone(self.store.claim())
        self.assertIsNone(self.store.claim_index())

    def test_index_retry_returns_to_parsed_and_preserves_artifact(self):
        self.store.submit(request()); row=self.store.claim()
        self.store.finish(row['id'],row['attempt'],'PARSED',artifact='prefix')
        with self.store.engine.begin() as db: db.execute(update(jobs).values(available_at=0))
        indexed=self.store.claim_index()
        self.store.finish(indexed['id'],indexed['attempt'],'FAILED',error='network',retry=True)
        saved=self.store.get(row['id'])
        self.assertEqual(saved['state'],'PARSED')
        self.assertEqual(saved['artifact_prefix'],'prefix')
    def test_api_auth_validation_and_cancel(self):
        token='x'*32
        with TestClient(create_app(Settings(self.url,token),self.store)) as client:
            self.assertEqual(client.get('/health/live').status_code,200)
            self.assertEqual(client.post('/internal/knowledge/jobs',json=request().model_dump()).status_code,401)
            headers={'Authorization':'Bearer '+token}
            self.assertEqual(client.get('/health/ready',headers=headers).status_code,200)
            self.assertEqual(client.post('/internal/knowledge/jobs',json=request().model_dump(),headers=headers).status_code,202)
            self.assertEqual(client.post('/internal/knowledge/jobs',json=request(sourceRevision='other').model_dump(),headers=headers).status_code,409)
            invalid=request().model_dump() | {'sourceUrl':'http://127.0.0.1/private'}
            self.assertEqual(client.post('/internal/knowledge/jobs',json=invalid,headers=headers).status_code,422)
            self.assertEqual(client.post('/internal/knowledge/jobs/job-00000001/cancel',headers=headers).json()['state'],'CANCELLED')
            self.assertEqual(client.get('/internal/knowledge/jobs/missing',headers=headers).status_code,404)


if __name__ == '__main__': unittest.main()
