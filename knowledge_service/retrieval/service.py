from __future__ import annotations

from agent_service.learning_agent.schemas import Evidence
from knowledge_service.indexing.retrieval import KnowledgeRetriever


class EvidenceRetriever:
    """Multi-query fusion above the existing active-version hybrid retriever."""
    def __init__(self, retriever: KnowledgeRetriever): self.retriever = retriever

    def search(self, owner_id: str, authorized_resource_ids: list[str], queries: list[str],
               limit: int = 12) -> tuple[str, list[Evidence]]:
        fused: dict[tuple[str, str, str], tuple[float, dict]] = {}
        snapshot = "empty"
        for query in queries[:3]:
            result = self.retriever.search(owner_id, authorized_resource_ids, query,
                                           parent_limit=5, child_limit=limit)
            snapshot = result.knowledgeSnapshotId if result.knowledgeSnapshotId != "empty" else snapshot
            for rank, hit in enumerate(result.childHits):
                payload = hit.get("payload", {})
                key = (str(payload.get("resourceId", "")), str(payload.get("indexRevision", "")),
                       str(payload.get("chunkId", "")))
                if not all(key): continue
                score = 1.0 / (60 + rank + 1)
                previous = fused.get(key)
                fused[key] = ((previous[0] if previous else 0.0) + score, payload)
        ranked = sorted(fused.values(), key=lambda item: item[0], reverse=True)[:limit]
        evidence = [Evidence(sourceId=f"S{i+1}", resourceId=str(p.get("resourceId")),
            indexRevision=str(p.get("indexRevision")), chunkId=str(p.get("chunkId")),
            parentId=p.get("parentId"), contentHash=str(p.get("contentHash", "")),
            titlePath=list(p.get("titlePath") or []), content=str(p.get("content", "")),
            locators=list(p.get("locators") or []), score=score)
            for i, (score, p) in enumerate(ranked)]
        return snapshot, evidence
