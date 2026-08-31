from __future__ import annotations

import pytest

from flowstate.knowledge.ingestion import IngestionService
from flowstate.knowledge.models import PaperIdentifiers, ProviderWork
from tests.knowledge.conftest import FakeEmbeddings


@pytest.mark.asyncio
async def test_retracted_work_is_rejected_and_not_indexed(test_config, store) -> None:
    service = IngestionService(test_config, store, FakeEmbeddings())
    work = ProviderWork(
        paper_id="huggingface:retracted-example",
        title="Retracted Example Paper",
        year=2021,
        identifiers=PaperIdentifiers(arxiv_id="retracted-example"),
        retracted=True,
        source="huggingface_papers",
        raw_response_hash="b" * 64,
    )
    await service.enqueue_provider_records([work], "retraction-check")
    receipts = await service.process_queue(resolve_code=False)
    assert len(receipts) == 1
    assert receipts[0].outcome == "rejected"
    assert receipts[0].error == "retracted work"
    assert store.get_paper("huggingface:retracted-example") is None
