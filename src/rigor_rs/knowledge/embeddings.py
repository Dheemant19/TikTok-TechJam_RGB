from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np
from fastembed import TextEmbedding

from rigor_rs.knowledge.config import EmbeddingConfig


class EmbeddingProvider(Protocol):
    model_id: str
    revision: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]: ...


class FastEmbedProvider:
    def __init__(self, config: EmbeddingConfig) -> None:
        self.config = config
        self.model_id = config.model
        self.revision = config.revision
        self.dimensions = config.dimensions
        self.cache_dir = config.model_manifest.parent / "fastembed"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._model: TextEmbedding | None = None

    def _load(self) -> TextEmbedding:
        if self._model is None:
            self._model = TextEmbedding(
                model_name=self.model_id,
                cache_dir=str(self.cache_dir),
                revision=self.revision,
                local_files_only=not self.config.allow_initial_download,
            )
            probe = np.asarray(next(iter(self._model.embed(["dimension probe"]))))
            if probe.shape != (self.dimensions,):
                raise ValueError(f"embedding dimension {probe.shape} does not match configured {self.dimensions}")
            self._write_manifest()
        return self._model

    def _write_manifest(self) -> None:
        files: list[dict[str, str | int]] = []
        for path in sorted(self.cache_dir.rglob("*")):
            if path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                files.append({
                    "path": str(path.relative_to(self.cache_dir)).replace("\\", "/"),
                    "bytes": path.stat().st_size,
                    "sha256": digest.hexdigest(),
                })
        document = {
            "embedding_model_id": self.model_id,
            "revision": self.revision,
            "dimensions": self.dimensions,
            "files": files,
        }
        self.config.model_manifest.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config.model_manifest.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.config.model_manifest)

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]:
        if not texts:
            return []
        vectors = [np.asarray(vector, dtype=np.float32) for vector in self._load().embed(list(texts))]
        if any(vector.shape != (self.dimensions,) for vector in vectors):
            raise ValueError("embedding service returned an unexpected dimension")
        return vectors


def vector_to_bytes(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype="<f4").tobytes(order="C")


def vector_from_bytes(value: bytes, dimension: int) -> np.ndarray:
    vector = np.frombuffer(value, dtype="<f4")
    if vector.shape != (dimension,):
        raise ValueError("stored vector dimension mismatch")
    return vector
