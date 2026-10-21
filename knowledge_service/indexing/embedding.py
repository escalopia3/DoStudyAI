from __future__ import annotations

from dataclasses import dataclass
import math
import os
from typing import Protocol, Sequence


class EmbeddingProvider(Protocol):
    @property
    def version(self) -> str: ...
    @property
    def dimension(self) -> int: ...
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def validate_vectors(vectors: Sequence[Sequence[float]], expected: int, dimension: int) -> None:
    if len(vectors) != expected:
        raise ValueError("EMBEDDING_COUNT_MISMATCH")
    for vector in vectors:
        if len(vector) != dimension:
            raise ValueError("EMBEDDING_DIMENSION_MISMATCH")
        if not vector or any(not math.isfinite(float(x)) for x in vector):
            raise ValueError("INVALID_EMBEDDING_VALUE")


@dataclass(frozen=True)
class LocalBgeM3Config:
    model_path: str
    model_revision: str
    dimension: int = 1024
    batch_size: int = 16
    normalize: bool = True
    max_length: int = 2048
    input_template_version: str = "parent-child-v1"
    device: str = "cpu"

    @property
    def version(self) -> str:
        norm = 1 if self.normalize else 0
        return f"local__bge-m3__{self.model_revision}__d{self.dimension}__norm{norm}__{self.input_template_version}"


class LocalBgeM3Provider:
    """Explicitly offline BGE-M3 adapter; construction is the only model-load point."""

    def __init__(self, config: LocalBgeM3Config):
        if config.dimension != 1024:
            raise ValueError("BGE-M3 output dimension must be 1024")
        if not config.model_path:
            raise ValueError("LEARNING_EMBEDDING_MODEL_PATH is required")
        if not os.path.isdir(config.model_path):
            raise ValueError("EMBEDDING_MODEL_DIRECTORY_MISSING")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("sentence-transformers is not installed") from exc
        self.config = config
        self.model = SentenceTransformer(config.model_path, device=config.device,
                                         local_files_only=True)
        self.model.max_seq_length = config.max_length

    @property
    def version(self) -> str: return self.config.version

    @property
    def dimension(self) -> int: return self.config.dimension

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        values = self.model.encode(list(texts), batch_size=self.config.batch_size,
                                   normalize_embeddings=self.config.normalize,
                                   show_progress_bar=False, convert_to_numpy=True)
        vectors = values.tolist()
        validate_vectors(vectors, len(texts), self.dimension)
        return vectors

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text])[0]

