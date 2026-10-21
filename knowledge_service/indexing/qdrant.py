from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Sequence

import httpx

from knowledge_service.indexing.chunking import Chunk


class QdrantRequestError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        super().__init__(f"Qdrant request failed ({status_code}): {detail[:500]}")


class QdrantIndex:
    def __init__(self, base_url: str, collection: str, dimension: int = 1024,
                 api_key: str = "", timeout: float = 30):
        headers = {"api-key": api_key} if api_key else {}
        self.http = httpx.Client(base_url=base_url.rstrip("/"), headers=headers,
                                 timeout=timeout, trust_env=False)
        self.collection, self.dimension = collection, dimension

    def close(self): self.http.close()

    def ensure_schema(self) -> None:
        response = self.http.get(f"/collections/{self.collection}")
        if response.status_code == 404:
            body = {
                "vectors": {"dense": {"size": self.dimension, "distance": "Cosine"}},
                "sparse_vectors": {"bm25": {"modifier": "idf"}},
            }
            self._ok(self.http.put(f"/collections/{self.collection}", json=body))
        else:
            self._ok(response)
            config = response.json()["result"]["config"]["params"]["vectors"]["dense"]
            if int(config["size"]) != self.dimension or str(config["distance"]).lower() != "cosine":
                raise ValueError("QDRANT_COLLECTION_SCHEMA_MISMATCH")
        for field in ("ownerId", "resourceId", "sourceRevision", "indexRevision",
                      "embeddingVersion", "chunkType", "parentId", "deleted"):
            schema = "bool" if field == "deleted" else "keyword"
            result = self.http.put(f"/collections/{self.collection}/index",
                                   json={"field_name": field, "field_schema": schema})
            if result.status_code not in (200, 201, 409): self._ok(result)

    @staticmethod
    def point_id(resource_id: str, index_revision: str, chunk_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"dovideo:{resource_id}:{index_revision}:{chunk_id}"))

    def upsert(self, owner_id: str, resource_id: str, source_revision: str,
               index_revision: str, embedding_version: str,
               chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]],
               batch_size: int = 64) -> None:
        if len(chunks) != len(vectors): raise ValueError("VECTOR_CHUNK_COUNT_MISMATCH")
        for start in range(0, len(chunks), batch_size):
            points = []
            for chunk, vector in zip(chunks[start:start+batch_size], vectors[start:start+batch_size]):
                payload = chunk.to_dict() | {
                    "ownerId": owner_id, "resourceId": resource_id,
                    "sourceRevision": source_revision, "indexRevision": index_revision,
                    "embeddingVersion": embedding_version, "deleted": False,
                }
                points.append({
                    "id": self.point_id(resource_id, index_revision, chunk.chunkId),
                    "vector": {
                        "dense": list(vector),
                        "bm25": {"text": chunk.embeddingText, "model": "Qdrant/bm25"},
                    },
                    "payload": payload,
                })
            self._ok(self.http.put(f"/collections/{self.collection}/points?wait=true",
                                   json={"points": points}))

    def count(self, resource_id: str, index_revision: str) -> int:
        response = self.http.post(f"/collections/{self.collection}/points/count",
            json={"filter": self._version_filter(resource_id, index_revision), "exact": True})
        self._ok(response)
        return int(response.json()["result"]["count"])

    def sample(self, resource_id: str, index_revision: str, limit: int = 10) -> list[dict[str, Any]]:
        response = self.http.post(f"/collections/{self.collection}/points/scroll", json={
            "filter": self._version_filter(resource_id, index_revision), "limit": limit,
            "with_payload": True, "with_vector": False})
        self._ok(response)
        return response.json()["result"]["points"]

    def query(self, query_vector: Sequence[float], query_text: str,
              owner_id: str, version_pairs: Sequence[tuple[str, str]],
              dense_limit: int = 30, sparse_limit: int = 30, limit: int = 12,
              chunk_type: str = "CHILD") -> list[dict[str, Any]]:
        if not owner_id or not version_pairs:
            return []
        version_should = [{"must": [
            {"key": "resourceId", "match": {"value": resource_id}},
            {"key": "indexRevision", "match": {"value": revision}},
        ]} for resource_id, revision in version_pairs]
        search_filter = {"must": [
            {"key": "ownerId", "match": {"value": owner_id}},
            {"key": "chunkType", "match": {"value": chunk_type}},
            {"key": "deleted", "match": {"value": False}},
            {"should": version_should},
        ]}
        body = {
            "prefetch": [
                {"query": list(query_vector), "using": "dense", "limit": dense_limit,
                 "filter": search_filter},
                {"query": {"text": query_text, "model": "Qdrant/bm25"},
                 "using": "bm25", "limit": sparse_limit, "filter": search_filter},
            ],
            "query": {"rrf": {}}, "limit": limit,
            "with_payload": True, "with_vector": False,
        }
        response = self.http.post(f"/collections/{self.collection}/points/query", json=body)
        self._ok(response)
        return response.json()["result"]["points"]

    @staticmethod
    def _version_filter(resource_id: str, index_revision: str) -> dict:
        return {"must": [
            {"key": "resourceId", "match": {"value": resource_id}},
            {"key": "indexRevision", "match": {"value": index_revision}},
        ]}

    @staticmethod
    def manifest_hash(chunks: Sequence[Chunk]) -> str:
        value = json.dumps([(x.chunkId, x.contentHash, x.parentId) for x in chunks],
                           separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _ok(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise QdrantRequestError(response.status_code, response.text)

