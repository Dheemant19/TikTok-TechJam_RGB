from __future__ import annotations

import json
from pathlib import Path

import pytest

from rigor_rs.knowledge.ingestion import IngestionService, ManifestValidationFailure, validate_manifest
from rigor_rs.knowledge.store import KnowledgeStore
from tests.knowledge.conftest import FakeEmbeddings


def test_validation_does_not_create_database(test_config, tmp_path: Path) -> None:
    database = tmp_path / "never-created.sqlite3"
    assert not database.exists()
    manifest = validate_manifest(test_config.curated_source.file, 25)
    assert len(manifest.papers) == 25
    assert not database.exists()


def test_validation_reports_field_location(test_config, tmp_path: Path) -> None:
    malformed = tmp_path / "bad.json"
    malformed.write_text(json.dumps({"schema_version": 1, "papers": [{"paper_id": "bad"}]}), encoding="utf-8")
    with pytest.raises(ManifestValidationFailure) as failure:
        validate_manifest(malformed)
    assert any(error["location"][:2] == ["papers", 0] for error in failure.value.errors)


@pytest.mark.asyncio
async def test_curated_ingestion_is_idempotent(test_config, store: KnowledgeStore) -> None:
    service = IngestionService(test_config, store, FakeEmbeddings())
    first = await service.ingest_curated(enrich=False, resolve_code=False)
    first_counts = store.counts()
    second = await service.ingest_curated(enrich=False, resolve_code=False)
    second_counts = store.counts()
    assert len(first) == len(second) == 25
    assert all(receipt.outcome == "inserted" for receipt in first)
    assert all(receipt.outcome == "unchanged" for receipt in second)
    for table in ("papers", "paper_versions", "paper_identifiers", "code_implementations", "paper_vectors"):
        assert second_counts[table] == first_counts[table]
    assert second_counts["ingestion_events"] == first_counts["ingestion_events"] + 25
