"""Infrastructure clients owned by one application process."""
import logging
from urllib.parse import urlsplit

EXPECTED_ALEMBIC_REVISION = "0012"
logger = logging.getLogger(__name__)

class Storage:
    def __init__(self, settings):
        from sqlalchemy import create_engine
        from minio import Minio
        from qdrant_client import QdrantClient
        self.engine = None
        self.minio = None
        self.qdrant = None
        self._minio_http = None
        try:
            self.engine = create_engine(settings.database_url, pool_pre_ping=True,
                                        connect_args={"connect_timeout": 3})
            endpoint = urlsplit(settings.minio_endpoint)
            if endpoint.scheme not in ("http", "https") or not endpoint.netloc:
                raise ValueError("DOVIDEO_MINIO_ENDPOINT must be an HTTP(S) URL")
            import urllib3
            self._minio_http = urllib3.PoolManager(
                timeout=urllib3.Timeout(connect=3, read=3), retries=False)
            self.minio = Minio(endpoint.netloc, access_key=settings.minio_access_key,
                               secret_key=settings.minio_secret_key,
                               secure=endpoint.scheme == "https", http_client=self._minio_http)
            self.qdrant = QdrantClient(url=settings.qdrant_url,
                                       api_key=settings.qdrant_api_key, timeout=60,
                                       check_compatibility=False,
                                       # Service endpoints are explicit; inherited desktop proxies
                                       # must not intercept private/local infrastructure traffic.
                                       trust_env=False)
            self.bucket = settings.minio_bucket
        except Exception:
            self.close()
            raise

    def ready(self):
        from sqlalchemy import text
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            if revisions != [EXPECTED_ALEMBIC_REVISION]:
                raise RuntimeError("Database migration revision mismatch")
        self.minio.list_buckets()
        self.qdrant.get_collections()

    def ensure_bucket(self):
        from minio.versioningconfig import VersioningConfig, ENABLED
        if not self.minio.bucket_exists(self.bucket):
            self.minio.make_bucket(self.bucket)
        self.minio.set_bucket_versioning(self.bucket, VersioningConfig(ENABLED))

    def close(self):
        # Shutdown is best-effort: one client failure must not leak the others.
        for name, action in (
            ("qdrant", lambda: self.qdrant and self.qdrant.close()),
            ("minio", lambda: self._minio_http and self._minio_http.clear()),
            ("postgres", lambda: self.engine and self.engine.dispose()),
        ):
            try:
                action()
            except Exception:
                logger.exception("Failed to close %s client", name)
