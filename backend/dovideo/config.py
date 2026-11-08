"""Read process environment and optional local runtime defaults."""
from dataclasses import dataclass, field
import os
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

def load_local_environment():
    """Load trusted project runtime defaults; explicit environment always wins."""
    path = PROJECT_ROOT / 'backend' / 'runtime.local.json'
    if not path.is_file():
        return
    values = json.loads(path.read_text(encoding='utf-8'))
    for key, value in values.items():
        if not isinstance(value, str) or not key.startswith(('DOVIDEO_', 'DOCLING_', 'HF_', 'TRANSFORMERS_')):
            raise ValueError('Invalid runtime configuration key/value')
        if key.endswith(('_PATH', '_FFMPEG')):
            candidate = Path(value)
            value = str(candidate if candidate.is_absolute() else PROJECT_ROOT / candidate)
        os.environ.setdefault(key, value)

@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    minio_endpoint: str
    minio_access_key: str = field(repr=False)
    minio_secret_key: str = field(repr=False)
    qdrant_url: str
    qdrant_api_key: str = field(repr=False)
    minio_bucket: str = "dovideo-v2"
    session_hours: int = 24
    upload_expiry_minutes: int = 30

    @classmethod
    def from_env(cls):
        load_local_environment()
        values = {key: os.environ.get("DOVIDEO_" + key, "") for key in
                  ("DATABASE_URL", "MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "QDRANT_URL", "QDRANT_API_KEY")}
        missing = [key for key, value in values.items() if not value]
        if missing:
            raise ValueError("Missing configuration: " + ", ".join("DOVIDEO_" + key for key in missing))
        if not values["DATABASE_URL"].startswith("postgresql+psycopg://"):
            raise ValueError("DOVIDEO_DATABASE_URL must use postgresql+psycopg://")
        return cls(**{key.lower(): value for key, value in values.items()},
                   minio_bucket=os.environ.get("DOVIDEO_MINIO_BUCKET", "dovideo-v2"),
                   session_hours=int(os.environ.get("DOVIDEO_SESSION_HOURS", "24")),
                   upload_expiry_minutes=int(os.environ.get("DOVIDEO_UPLOAD_EXPIRY_MINUTES", "30")))
