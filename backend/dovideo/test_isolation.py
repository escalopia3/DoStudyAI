"""Fail closed before integration fixtures can write to a learning workspace."""
from sqlalchemy.engine import make_url

def require_test_storage(settings):
    database = make_url(settings.database_url).database or ''
    if not database.endswith('_test') or not settings.minio_bucket.endswith('-test'):
        raise ValueError('Integration tests require a database ending in _test and a bucket ending in -test; refusing to write learning data')
