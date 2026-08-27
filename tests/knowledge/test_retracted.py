from __future__ import annotations

import pytest

from rigor_rs.knowledge.ingestion import IngestionService
from rigor_rs.knowledge.models import PaperIdentifiers, ProviderWork
from tests.knowledge.conftest import FakeEmbeddings


@pytest.mark.asyncio
async def test_retracted_work_is_rejected_and_not_indexed(test_config, store) -> None:
    service = IngestionService(test_config, store, FakeEmbeddings())
    work = ProviderWork(
        paper_id="openalex:retracted-example",
        title="Retracted Example Paper",
        year=2021,
        identifiers=PaperIdentifiers(openalex_id="RETRACTED1"),
        retracted=True,
        source="openalex",
        raw_response_hash="b" * 64,
    )
    await service.enqueue_provider_records([work], "retraction-check")
    receipts = await service.process_queue(resolve_code=False)
    assert len(receipts) == 1
    assert receipts[0].outcome == "rejected"
    assert receipts[0].error == "retracted work"
    assert store.get_paper("openalex:retracted-example") is None
