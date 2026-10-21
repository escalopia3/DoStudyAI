"""Run with python -m agent_service.worker; no work is launched from API requests."""
import json
import hashlib
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
import threading
from contextlib import ExitStack
from pathlib import Path
import httpx
from urllib3 import PoolManager, Timeout
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from agent_service.config import Settings
from agent_service.store import Store, events

log = logging.getLogger("learning.worker")


class Worker:
    def __init__(self, settings, store):
        from minio import Minio
        from minio.error import S3Error
        self.storage_error_types = (S3Error,)
        self.settings, self.store = settings, store
        self.stopping = False
        self.http = httpx.Client(base_url=settings.java_url, timeout=30,
            headers={"Authorization": "Bearer " + settings.token}, follow_redirects=False,
            # Java is a loopback service in local deployments. Do not send
            # internal authenticated traffic through a user/system HTTP proxy.
            trust_env=False)
        self.objects = Minio(os.environ["LEARNING_MINIO_ENDPOINT"],
            access_key=os.environ["LEARNING_MINIO_ACCESS_KEY"],
            secret_key=os.environ["LEARNING_MINIO_SECRET_KEY"],
            secure=os.getenv("LEARNING_MINIO_SECURE", "true").lower() == "true",
            http_client=PoolManager(timeout=Timeout(connect=5, read=20), retries=False))
        self.bucket = os.getenv("LEARNING_MINIO_BUCKET", "media")
        self._index_components = None

    def callback_once(self):
        with self.store.engine.connect() as db:
            row = db.execute(select(events).where(events.c.delivered == 0,
                events.c.available_at <= time.time()).order_by(events.c.available_at).limit(1)).mappings().first()
        if not row: return
        try:
            response = self.http.post("/internal/learning/knowledge-events", json=json.loads(row["payload"]))
            response.raise_for_status()
            changes = dict(delivered=1)
        except httpx.HTTPError:
            count = row["attempts"] + 1
            changes = dict(attempts=count, available_at=time.time()+min(3600, 2**min(count, 12)))
            if count >= 20: changes["delivered"] = -1  # operator replay required
            log.warning("knowledge_callback_failed eventId=%s attempts=%s", row["id"], count)
        with self.store.engine.begin() as db:
            db.execute(update(events).where(events.c.id == row["id"], events.c.delivered == 0).values(**changes))

    def source(self, request):
        response = self.http.get(f'/internal/learning/jobs/{request["jobId"]}/source')
        response.raise_for_status()
        data = response.json()
        for key in ("resourceId", "userId", "courseId", "sourceRevision", "sourceType"):
            if data.get(key) != request[key]: raise ValueError("SOURCE_CHANGED")
        return data

    def run_once(self):
        row = self.store.claim(self.settings.lease_seconds, self.settings.max_attempts)
        if not row: return False
        request = json.loads(row["payload"])
        proc = None
        heartbeat_stop = threading.Event()
        lease_lost = threading.Event()
        def heartbeat():
            while not heartbeat_stop.wait(max(1, self.settings.lease_seconds // 3)):
                try:
                    if not self.store.renew(row["id"], row["attempt"], self.settings.lease_seconds):
                        lease_lost.set(); return
                except Exception:
                    lease_lost.set(); return
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        def stop_process():
            if proc and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
        try:
            self.settings.work_dir.mkdir(parents=True, exist_ok=True)
            with ExitStack() as stack:
                temp = stack.enter_context(tempfile.TemporaryDirectory(dir=self.settings.work_dir, prefix="parse-"))
                # LIFO: kill parser before closing its log and deleting its directory (Windows).
                directory = Path(temp).resolve()
                data = self.source(request)
                suffix = ".json" if request["sourceType"] == "VIDEO" else "."+request["sourceType"].lower()
                source = directory / ("source"+suffix)
                if suffix == ".json":
                    content = json.dumps(data["videoContext"]).encode()
                    if len(content) > self.settings.max_bytes: raise ValueError("FILE_SIZE_LIMIT")
                    source.write_bytes(content)
                else:
                    key = data["objectKey"]
                    if not key.startswith(f'learning/{request["userId"]}/') or ".." in key:
                        raise ValueError("INVALID_OBJECT_KEY")
                    stream = self.objects.get_object(self.bucket, key)
                    try:
                        total = 0
                        with source.open("wb") as out:
                            for chunk in stream.stream(1024*1024):
                                total += len(chunk)
                                if total > self.settings.max_bytes: raise ValueError("FILE_SIZE_LIMIT")
                                if not self.store.renew(row["id"], row["attempt"], self.settings.lease_seconds):
                                    raise ValueError("LEASE_LOST")
                                out.write(chunk)
                    finally:
                        stream.close()
                        stream.release_conn()
                output = directory / "artifacts"
                parser_log = stack.enter_context((directory / "parser.log").open("wb"))
                stack.callback(stop_process)
                proc = subprocess.Popen([sys.executable, "-m", "knowledge_service.parsing.convert",
                    str(source), request["sourceRevision"], str(output), "--artifacts", self.settings.artifacts_path,
                    "--timeout", str(self.settings.timeout), "--max-pages", str(self.settings.max_pages)],
                    stdout=parser_log, stderr=parser_log)
                deadline = time.monotonic() + self.settings.timeout
                while proc.poll() is None:
                    if self.stopping or lease_lost.is_set() or time.monotonic() >= deadline:
                        raise ValueError("PARSE_TIMEOUT_OR_SHUTDOWN")
                    if not self.store.renew(row["id"], row["attempt"], self.settings.lease_seconds):
                        raise ValueError("LEASE_LOST")
                    time.sleep(1)
                if proc.returncode:
                    parser_log.flush()
                    try:
                        details = (directory / "parser.log").read_text(
                            encoding="utf-8", errors="replace"
                        )[-4000:]
                    except OSError:
                        details = "parser log unavailable"
                    log.error(
                        "parser_process_failed jobId=%s exitCode=%s logTail=%s",
                        row["id"], proc.returncode, details
                    )
                    raise ValueError("PARSER_FAILED")
                self.source(request)  # revoke/replace check before publishing
                prefix = f'learning-artifacts/{request["resourceId"]}/{request["sourceRevision"]}/{row["id"]}/{row["attempt"]}'
                for artifact in output.iterdir():
                    if not self.store.renew(row["id"], row["attempt"], self.settings.lease_seconds):
                        raise ValueError("LEASE_LOST")
                    self.objects.fput_object(self.bucket, prefix+"/"+artifact.name, str(artifact))
                self.store.finish(row["id"], row["attempt"], "PARSED", artifact=prefix)
        except Exception as error:
            code = str(error) if isinstance(error, ValueError) else "DEPENDENCY_ERROR"
            transient = isinstance(error, (httpx.TransportError,) + self.storage_error_types) or (
                isinstance(error, httpx.HTTPStatusError) and error.response.status_code >= 500)
            retry = transient and row["attempt"] < self.settings.max_attempts
            self.store.finish(row["id"], row["attempt"], "FAILED", error=code[:64], retry=retry)
            log.warning("parse_failed jobId=%s attempt=%s code=%s", row["id"], row["attempt"], code[:64])
        finally:
            heartbeat_stop.set()
            thread.join(timeout=5)
            stop_process()
        return True

    @staticmethod
    def index_revision(request, embedding_version):
        value = "\0".join((request["resourceId"], request["sourceRevision"], embedding_version))
        return "idx-" + hashlib.sha256(value.encode()).hexdigest()[:48]

    def index_components(self):
        """Load the pinned local model lazily, then reuse it for later jobs."""
        if self._index_components is not None:
            return self._index_components
        from knowledge_service.indexing.embedding import LocalBgeM3Config, LocalBgeM3Provider
        from knowledge_service.indexing.qdrant import QdrantIndex
        from knowledge_service.indexing.store import IndexStore
        config = LocalBgeM3Config(
            model_path=os.environ["LEARNING_EMBEDDING_MODEL_PATH"],
            model_revision=os.environ["LEARNING_EMBEDDING_MODEL_REVISION"],
            dimension=int(os.getenv("LEARNING_EMBEDDING_DIMENSION", "1024")),
            batch_size=int(os.getenv("LEARNING_EMBEDDING_BATCH_SIZE", "16")),
            device=os.getenv("LEARNING_EMBEDDING_DEVICE", "cpu"))
        self._index_components = (
            IndexStore(self.settings.database_url),
            QdrantIndex(os.getenv("LEARNING_QDRANT_URL", "http://127.0.0.1:6333"),
                os.getenv("LEARNING_QDRANT_COLLECTION", "course_knowledge_bge_m3_d1024_v1"),
                config.dimension, os.getenv("LEARNING_QDRANT_API_KEY", "")),
            LocalBgeM3Provider(config))
        return self._index_components

    def index_once(self):
        row = self.store.claim_index(self.settings.lease_seconds, self.settings.max_attempts)
        if not row: return False
        request = json.loads(row["payload"])
        heartbeat_stop = threading.Event()
        lease_lost = threading.Event()

        def heartbeat():
            while not heartbeat_stop.wait(max(1, self.settings.lease_seconds // 3)):
                try:
                    if not self.store.renew(row["id"], row["attempt"], self.settings.lease_seconds):
                        lease_lost.set(); return
                except Exception:
                    lease_lost.set(); return

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            prefix = row.get("artifact_prefix") or ""
            expected = (f'learning-artifacts/{request["resourceId"]}/'
                        f'{request["sourceRevision"]}/{row["id"]}/')
            if not prefix.startswith(expected): raise ValueError("INVALID_ARTIFACT_PREFIX")
            self.source(request)
            self.settings.work_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.settings.work_dir, prefix="index-") as temp:
                document_path = Path(temp) / "document.json"
                self.objects.fget_object(self.bucket, prefix + "/document.json", str(document_path))
                from knowledge_service.indexing.pipeline import BuildRequest, IndexPipeline, load_document
                index_store, qdrant, embeddings = self.index_components()
                active = index_store.active([request["resourceId"]])
                previous = active[0]["index_revision"] if active else None
                revision = self.index_revision(request, embeddings.version)

                def fence():
                    if self.stopping or lease_lost.is_set(): raise ValueError("LEASE_LOST")
                    if not self.store.renew(row["id"], row["attempt"], self.settings.lease_seconds):
                        raise ValueError("LEASE_LOST")
                    self.source(request)

                IndexPipeline(index_store, qdrant, embeddings).build_and_publish(
                    load_document(document_path), BuildRequest(
                        request["userId"], request["resourceId"], request["sourceRevision"],
                        revision, previous), before_publish=fence)
                if not self.store.finish(row["id"], row["attempt"], "READY", artifact=prefix):
                    raise ValueError("LEASE_LOST")
        except Exception as error:
            code = str(error) if isinstance(error, ValueError) else "INDEX_DEPENDENCY_ERROR"
            from knowledge_service.indexing.qdrant import QdrantRequestError
            transient = isinstance(error, (httpx.TransportError,) + self.storage_error_types) or (
                isinstance(error, httpx.HTTPStatusError) and error.response.status_code >= 500) or (
                isinstance(error, QdrantRequestError) and error.status_code >= 500) or isinstance(error, SQLAlchemyError)
            retry = transient and row["attempt"] < self.settings.max_attempts
            self.store.finish(row["id"], row["attempt"], "FAILED", error=code[:64], retry=retry)
            log.warning("index_failed jobId=%s attempt=%s code=%s", row["id"], row["attempt"], code[:64])
        finally:
            heartbeat_stop.set()
            thread.join(timeout=5)
        return True

    def close(self):
        if self._index_components is not None:
            self._index_components[1].close()
        if hasattr(self, "http"):
            self.http.close()


def main():
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    worker = Worker(settings, Store(settings.database_url))
    def stop(*_): worker.stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not worker.stopping:
        try:
            worker.callback_once()
            worked = worker.run_once()
            worked = worker.index_once() or worked
            if not worked: time.sleep(1)
        except Exception:
            # Include the underlying database/network error so local operators
            # can distinguish a missing migration from an unavailable service.
            log.exception("worker_dependency_unavailable")
            time.sleep(5)
    worker.close()


if __name__ == "__main__": main()
