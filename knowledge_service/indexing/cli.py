"""Explicit local indexing command. It never downloads models or dependencies."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from knowledge_service.indexing.embedding import LocalBgeM3Config, LocalBgeM3Provider
from knowledge_service.indexing.pipeline import BuildRequest, IndexPipeline, load_document
from knowledge_service.indexing.qdrant import QdrantIndex
from knowledge_service.indexing.store import IndexStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("document", type=Path, help="normalized document.json")
    parser.add_argument("--owner-id", required=True)
    parser.add_argument("--resource-id", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--index-revision", required=True)
    parser.add_argument("--expected-previous")
    args = parser.parse_args()
    config = LocalBgeM3Config(
        model_path=os.environ["LEARNING_EMBEDDING_MODEL_PATH"],
        model_revision=os.environ["LEARNING_EMBEDDING_MODEL_REVISION"],
        dimension=int(os.getenv("LEARNING_EMBEDDING_DIMENSION", "1024")),
        batch_size=int(os.getenv("LEARNING_EMBEDDING_BATCH_SIZE", "16")),
        device=os.getenv("LEARNING_EMBEDDING_DEVICE", "cpu"))
    provider = LocalBgeM3Provider(config)
    qdrant = QdrantIndex(os.getenv("LEARNING_QDRANT_URL", "http://127.0.0.1:6333"),
        os.getenv("LEARNING_QDRANT_COLLECTION", "course_knowledge_bge_m3_d1024_v1"),
        config.dimension, os.getenv("LEARNING_QDRANT_API_KEY", ""))
    try:
        pipeline = IndexPipeline(IndexStore(os.environ["LEARNING_DATABASE_URL"]), qdrant, provider)
        result = pipeline.build_and_publish(load_document(args.document), BuildRequest(
            args.owner_id, args.resource_id, args.source_revision, args.index_revision,
            args.expected_previous))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        qdrant.close()


if __name__ == "__main__": main()
