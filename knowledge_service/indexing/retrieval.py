from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from knowledge_service.indexing.embedding import EmbeddingProvider
from knowledge_service.indexing.qdrant import QdrantIndex
from knowledge_service.indexing.store import IndexStore


@dataclass(frozen=True)
class RetrievalResult:
    knowledgeSnapshotId: str
    parentHits: list[dict[str, Any]]
    childHits: list[dict[str, Any]]


class KnowledgeRetriever:
    """Only searches caller-authorized resources at their published revisions."""

    def __init__(self, store: IndexStore, qdrant: QdrantIndex, embeddings: EmbeddingProvider):
        self.store, self.qdrant, self.embeddings = store, qdrant, embeddings

    def search(self, owner_id: str, authorized_resource_ids: list[str], question: str,
               parent_limit: int = 5, child_limit: int = 12) -> RetrievalResult:
        if not owner_id or not authorized_resource_ids:
            return RetrievalResult("empty", [], [])
        active = self.store.active(list(dict.fromkeys(authorized_resource_ids)))
        active_by_id = {row["resource_id"]: row for row in active}
        pairs = [(resource_id, active_by_id[resource_id]["index_revision"])
                 for resource_id in authorized_resource_ids if resource_id in active_by_id]
        if not pairs:
            return RetrievalResult("empty", [], [])
        vector = self.embeddings.embed_query(question)
        snapshot = self._snapshot(owner_id, pairs)
        parents = self.qdrant.query(vector, question, owner_id, pairs,
                                     dense_limit=10, sparse_limit=10,
                                     limit=parent_limit, chunk_type="PARENT")
        children = self.qdrant.query(vector, question, owner_id, pairs,
                                      dense_limit=30, sparse_limit=30,
                                      limit=child_limit, chunk_type="CHILD")
        return RetrievalResult(snapshot, parents, children)

    @staticmethod
    def _snapshot(owner_id: str, pairs: list[tuple[str, str]]) -> str:
        import hashlib
        canonical = owner_id + "\0" + "\0".join(f"{r}:{v}" for r, v in sorted(pairs))
        return "snapshot-" + hashlib.sha256(canonical.encode()).hexdigest()[:32]

