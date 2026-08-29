from __future__ import annotations

import pytest

from rigor_rs.knowledge.budgets import BudgetManager
from rigor_rs.knowledge.cache import QueryCache
from rigor_rs.knowledge.config import load_budget_config
from rigor_rs.knowledge.context import compile_evidence_context, validate_cited_evidence
from rigor_rs.knowledge.ingestion import IngestionService
from rigor_rs.knowledge.models import CacheStatus, EvidenceFilters, PaperIdentifiers, ProviderResult, ProviderWork, SourceMode
from rigor_rs.knowledge.retrieval import RetrievalService
from tests.knowledge.conftest import FakeEmbeddings


@pytest.fixture
async def retrieval(test_config, store):
    embeddings = FakeEmbeddings()
    ingestion = IngestionService(test_config, store, embeddings)
    await ingestion.ingest_curated()
    budgets = BudgetManager(store, load_budget_config(test_config.budget_config).mcp)
    cache = QueryCache(store, test_config.retrieval.cache_ttl_seconds)
    return RetrievalService(test_config, store, embeddings, budgets, cache, ingestion)


@pytest.mark.asyncio
async def test_exact_semantic_and_filtered_search_are_stable(retrieval) -> None:
    exact = await retrieval.search_evidence("GAUC", semantic=False, max_results=5)
    semantic = await retrieval.search_evidence("loss aligned with within-user ranking", semantic=True, max_results=5)
    filtered = await retrieval.search_evidence(
        "ranking", semantic=True,
        filters=EvidenceFilters(priority_area="ranking_loss_alignment"), max_results=5,
    )
    assert exact.results
    assert semantic.results
    assert filtered.results
    assert all("ranking_loss_alignment" in result.paper.priority_areas for result in filtered.results)
    repeated = await retrieval.search_evidence("  gauc ", semantic=False, max_results=5)
    assert repeated.meta.cache_status == CacheStatus.HIT
    assert [item.paper.paper_id for item in exact.results] == [item.paper.paper_id for item in repeated.results]


@pytest.mark.asyncio
async def test_zero_match_query_is_never_cached(retrieval) -> None:
    # A query that genuinely finds nothing right now must stay re-queryable
    # instead of permanently freezing an empty result for cache_ttl_seconds
    # while the corpus keeps growing via ingestion elsewhere.
    first = await retrieval.search_evidence(
        "zzz_no_such_term_xyz_unmatched", semantic=False, max_results=5,
    )
    second = await retrieval.search_evidence(
        "zzz_no_such_term_xyz_unmatched", semantic=False, max_results=5,
    )

    assert first.results == []
    assert first.meta.cache_status == CacheStatus.MISS
    assert second.results == []
    assert second.meta.cache_status == CacheStatus.MISS



@pytest.mark.asyncio
async def test_search_evidence_isolates_budget_by_explicit_session_and_experiment(retrieval) -> None:
    # KnowledgeRuntime previously hardcoded session_id/experiment_id to the
    # literal "standalone" for every real workflow run, so every session's
    # research calls shared one permanent budget bucket that never reset and
    # eventually silently zeroed out evidence for every future experiment.
    before = retrieval.budgets.usage("standalone", "standalone")
    await retrieval.search_evidence(
        "pairwise ranking", semantic=False, max_results=3,
        session_id="session-A", experiment_id="experiment-A",
    )

    after_standalone = retrieval.budgets.usage("standalone", "standalone")
    after_scoped = retrieval.budgets.usage("session-A", "experiment-A")
    assert after_standalone.session_provider_requests == before.session_provider_requests
    assert after_standalone.session_documents == before.session_documents
    assert after_scoped.session_documents > 0


@pytest.mark.asyncio
async def test_context_rejects_unknown_citations(retrieval) -> None:
    result = await retrieval.search_evidence("pairwise ranking", max_results=4)
    context = compile_evidence_context(result, 4, 20_000)
    validate_cited_evidence(context.evidence_ids, context)
    with pytest.raises(ValueError, match="not supplied"):
        validate_cited_evidence(["fabricated-paper"], context)


@pytest.mark.asyncio
async def test_unpinned_code_is_withheld(retrieval) -> None:
    result = await retrieval.get_code_for_paper("arxiv:1205.2618")
    assert result.results == []
    assert result.meta.warnings


class FakeOpenAlex:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query, filters, limit):
        self.calls += 1
        return ProviderResult(records=[ProviderWork(
            paper_id="openalex:w-test-live",
            title="Unique Live Provider Evidence",
            year=2025,
            identifiers=PaperIdentifiers(openalex_id="W-TEST-LIVE"),
            paper_url="https://openalex.org/W-TEST-LIVE",
            source="openalex",
            source_url="https://openalex.org/W-TEST-LIVE",
            raw_response_hash="a" * 64,
        )])


@pytest.mark.asyncio
async def test_local_miss_fetches_once_then_uses_cache(test_config, store) -> None:
    embeddings = FakeEmbeddings()
    provider = FakeOpenAlex()
    ingestion = IngestionService(test_config, store, embeddings)
    budgets = BudgetManager(store, load_budget_config(test_config.budget_config).mcp)
    cache = QueryCache(store, test_config.retrieval.cache_ttl_seconds)
    retrieval = RetrievalService(
        test_config, store, embeddings, budgets, cache, ingestion, openalex=provider,
    )
    first = await retrieval.search_evidence(
        "Unique Live Provider Evidence", semantic=False, max_results=3,
    )
    second = await retrieval.search_evidence(
        " unique   live provider evidence ", semantic=False, max_results=3,
    )
    assert provider.calls == 1
    assert first.meta.source_mode == SourceMode.LIVE
    assert first.results[0].paper.paper_id == "openalex:w-test-live"
    assert second.meta.cache_status == CacheStatus.HIT
