from __future__ import annotations

import json
from pathlib import Path

import pytest

from flowstate.knowledge.ingestion import IngestionService, ManifestValidationFailure, validate_manifest
from flowstate.knowledge.store import KnowledgeStore
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


@pytest.mark.asyncio
async def test_ensure_curated_bank_resolves_once_then_skips_network_calls(test_config, store: KnowledgeStore) -> None:
    from flowstate.knowledge.models import CodeRecord

    class FakeGitHub:
        def __init__(self) -> None:
            self.calls = 0

        async def resolve_repository(self, repository_url: str, paper_id: str | None = None) -> CodeRecord:
            self.calls += 1
            return CodeRecord(
                repository_url=repository_url, pinned_commit="d" * 40, license="MIT",
                stars=1, paper_id=paper_id, source_url=repository_url,
                retrieved_at="2026-01-01T00:00:00+00:00", content_hash=f"hash-{self.calls}".ljust(64, "0"),
                verified=True,
            )

    github = FakeGitHub()
    service = IngestionService(test_config, store, FakeEmbeddings(), github=github)
    manifest = validate_manifest(test_config.curated_source.file, test_config.curated_source.expected_paper_count)
    expected_resolvable = len([paper for paper in manifest.papers if paper.github_repositories])

    first = await service.ensure_curated_bank()
    assert len(first) == expected_resolvable
    assert github.calls == expected_resolvable
    assert store.papers_missing_verified_code([paper.paper_id for paper in manifest.papers if paper.github_repositories]) == set()

    second = await service.ensure_curated_bank()
    assert second == []
    assert github.calls == expected_resolvable
