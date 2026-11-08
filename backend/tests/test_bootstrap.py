import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.gateway import create_app
from dovideo.config import Settings
from dovideo.storage import Storage

class FakeStorage:
    def __init__(self, settings): self.closed = False
    def ready(self): pass
    def ensure_bucket(self): pass
    def close(self): self.closed = True

class BootstrapTests(unittest.TestCase):
    def test_configuration_fails_without_secrets(self):
        with patch.dict(os.environ, {}, clear=True), patch('dovideo.config.load_local_environment'):
            with self.assertRaisesRegex(ValueError, "Missing configuration"):
                Settings.from_env()

    def test_health_and_cleanup(self):
        storage = FakeStorage(None)
        with TestClient(create_app(object(), lambda settings: storage)) as client:
            response = client.get("/health/ready")
            self.assertEqual(response.status_code, 200)
            self.assertIn("X-Request-ID", response.headers)
        self.assertTrue(storage.closed)

    def test_unavailable_storage(self):
        class FailedStorage(FakeStorage):
            def ready(self): raise RuntimeError("secret must not leak")
        with TestClient(create_app(object(), FailedStorage)) as client:
            response = client.get("/health/ready")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("secret", response.text)

    def test_agent_graph_available(self):
        from dovideo.agents.agent import agent
        self.assertIn('model',agent.nodes)
        self.assertIn('tools',agent.nodes)

    def test_storage_close_releases_every_client(self):
        released = []
        storage = Storage.__new__(Storage)
        storage.qdrant = type("Q", (), {"close": lambda self: (_ for _ in ()).throw(RuntimeError())})()
        storage._minio_http = type("M", (), {"clear": lambda self: released.append("minio")})()
        storage.engine = type("E", (), {"dispose": lambda self: released.append("postgres")})()
        with self.assertLogs("dovideo.storage", level="ERROR"):
            storage.close()
        self.assertEqual(released, ["minio", "postgres"])
