from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

from knowledge_service.indexing.chunking import HierarchicalChunker
from knowledge_service.indexing.embedding import EmbeddingProvider, validate_vectors
from knowledge_service.indexing.qdrant import QdrantIndex
from knowledge_service.indexing.store import IndexStore


@dataclass(frozen=True)
class BuildRequest:
    owner_id: str
    resource_id: str
    source_revision: str
    index_revision: str
    expected_previous: str | None = None


class IndexPipeline:
    def __init__(self, store: IndexStore, qdrant: QdrantIndex,
                 embeddings: EmbeddingProvider, chunker: HierarchicalChunker | None = None):
        self.store, self.qdrant, self.embeddings = store, qdrant, embeddings
        self.chunker = chunker or HierarchicalChunker()

    def build_and_publish(self, document: dict[str, Any], request: BuildRequest,
                          before_publish: Callable[[], None] | None = None) -> dict[str, Any]:
        if document.get("resourceRevisionId") != request.source_revision:
            raise ValueError("SOURCE_REVISION_MISMATCH")
        bundle = self.chunker.build(document)
        chunks = [*bundle.parents, *bundle.children]
        self.store.begin(request.resource_id, request.source_revision,
                         request.index_revision, self.embeddings.version)
        self.qdrant.ensure_schema()
        vectors = self.embeddings.embed_documents([x.embeddingText for x in chunks])
        validate_vectors(vectors, len(chunks), self.embeddings.dimension)
        self.qdrant.upsert(request.owner_id, request.resource_id, request.source_revision,
                           request.index_revision, self.embeddings.version, chunks, vectors)
        actual = self.qdrant.count(request.resource_id, request.index_revision)
        expected = len(chunks)
        if actual != expected: raise ValueError("QDRANT_POINT_COUNT_MISMATCH")
        samples = self.qdrant.sample(request.resource_id, request.index_revision, min(10, expected))
        known = {x.chunkId: x.contentHash for x in chunks}
        for sample in samples:
            payload = sample.get("payload", {})
            if known.get(payload.get("chunkId")) != payload.get("contentHash"):
                raise ValueError("QDRANT_SAMPLE_MISMATCH")
        manifest = {
            "schemaVersion": "1", "resourceId": request.resource_id,
            "sourceRevision": request.source_revision, "indexRevision": request.index_revision,
            "embeddingVersion": self.embeddings.version,
            "expectedParentCount": len(bundle.parents), "expectedChildCount": len(bundle.children),
            "writtenPointCount": actual, "dimension": self.embeddings.dimension,
            "contentManifestHash": self.qdrant.manifest_hash(chunks),
        }
        self.store.mark_verified(request.index_revision, manifest)
        # Fence the active-pointer update after expensive vector writes. Worker
        # callers use this to re-check the source, cancellation, and lease.
        if before_publish:
            before_publish()
        manifest["generation"] = self.store.publish(request.resource_id, request.source_revision,
                                                      request.index_revision, request.expected_previous)
        return manifest


def load_document(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schemaVersion") != "1": raise ValueError("UNSUPPORTED_DOCUMENT_SCHEMA")
    return data

