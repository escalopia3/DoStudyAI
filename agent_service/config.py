import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    token: str
    java_url: str = "http://127.0.0.1:9090"
    work_dir: Path = Path(".learning-work")
    artifacts_path: str = ""
    max_bytes: int = 50 * 1024 * 1024
    max_pages: int = 500
    timeout: int = 300
    lease_seconds: int = 45
    max_attempts: int = 3

    @classmethod
    def from_env(cls):
        token = os.environ.get("LEARNING_SERVICE_TOKEN", "")
        if len(token) < 32:
            raise ValueError("LEARNING_SERVICE_TOKEN must contain at least 32 characters")
        url = os.environ["LEARNING_DATABASE_URL"]
        if not url.startswith("mysql+pymysql://"):
            raise ValueError("Production requires mysql+pymysql; use the shared media_db with ai_* tables")
        limits = {name: int(os.getenv(env, str(default))) for name, env, default in [
            ("max_bytes", "LEARNING_MAX_BYTES", 50*1024*1024),
            ("max_pages", "LEARNING_MAX_PAGES", 500),
            ("timeout", "LEARNING_PARSE_TIMEOUT", 300),
            ("lease_seconds", "LEARNING_LEASE_SECONDS", 45),
            ("max_attempts", "LEARNING_MAX_ATTEMPTS", 3)]}
        if any(value < 1 for value in limits.values()):
            raise ValueError("Learning worker limits must be positive")
        if limits["max_bytes"] > 50*1024*1024:
            raise ValueError("Parser hard limit is 50 MiB")
        return cls(url, token, os.getenv("LEARNING_JAVA_URL", "http://127.0.0.1:9090"),
                   Path(os.getenv("LEARNING_WORK_DIR", ".learning-work")),
                   os.getenv("DOCLING_ARTIFACTS_PATH", ""), **limits)
