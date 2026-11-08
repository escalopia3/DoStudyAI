import unittest
from types import SimpleNamespace
from dovideo.test_isolation import require_test_storage

class IsolationTests(unittest.TestCase):
    def test_rejects_learning_database_or_bucket(self):
        for database,bucket in [('dovideo_v2','dovideo-v2'),('dovideo_test','dovideo-v2'),('dovideo_v2','dovideo-test')]:
            with self.assertRaises(ValueError):
                require_test_storage(SimpleNamespace(database_url=f'postgresql+psycopg://localhost/{database}',minio_bucket=bucket))

    def test_accepts_explicit_test_storage(self):
        require_test_storage(SimpleNamespace(database_url='postgresql+psycopg://localhost/dovideo_test',minio_bucket='dovideo-test'))
