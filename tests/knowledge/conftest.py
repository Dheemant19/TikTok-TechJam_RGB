from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from rigor_rs.knowledge.config import KnowledgeConfig, load_knowledge_config
from rigor_rs.knowledge.store import KnowledgeStore


class FakeEmbeddings:
    model_id = "test-embedding"
    revision = "test-revision"
    dimensions = 16

    def embed(self, texts):
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            vector = np.frombuffer(digest[: self.dimensions], dtype=np.uint8).astype(np.float32)
            vector = (vector - vector.mean()) / (vector.std() or 1.0)
            vectors.append(vector)
        return vectors


@pytest.fixture
def test_config(tmp_path: Path) -> KnowledgeConfig:
    config = load_knowledge_config()
    data = config.model_dump()
    data["storage"]["database"] = tmp_path / "knowledge.sqlite3"
    data["embedding"]["model_manifest"] = tmp_path / "models/manifest.json"
    data["embedding"]["dimensions"] = 16
    data["embedding"]["allow_initial_download"] = False
    data["providers"]["openalex"]["enabled"] = False
    data["providers"]["github"]["enabled"] = False
    return KnowledgeConfig.model_validate(data)


@pytest.fixture
def store(test_config: KnowledgeConfig) -> KnowledgeStore:
    result = KnowledgeStore(test_config.storage.database)
    result.migrate()
    return result
