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


@pytest.mark.asyncio
async def test_bypass_cache_forces_a_fresh_live_fetch_every_call(test_config, store) -> None:
    # The per-experiment research() call must find current evidence every
    # time it runs, not replay whatever the first call for an (area, day)
    # pair happened to return up to cache_ttl_seconds (7 days) ago.
    embeddings = FakeEmbeddings()
    provider = FakeOpenAlex()
    ingestion = IngestionService(test_config, store, embeddings)
    budgets = BudgetManager(store, load_budget_config(test_config.budget_config).mcp)
    cache = QueryCache(store, test_config.retrieval.cache_ttl_seconds)
    retrieval = RetrievalService(
        test_config, store, embeddings, budgets, cache, ingestion, openalex=provider,
    )
    first = await retrieval.search_evidence(
        "Unique Live Provider Evidence", semantic=False, max_results=3, bypass_cache=True,
    )
    second = await retrieval.search_evidence(
        "Unique Live Provider Evidence", semantic=False, max_results=3, bypass_cache=True,
    )
    assert provider.calls == 2
    assert first.meta.cache_status == CacheStatus.MISS
    assert second.meta.cache_status == CacheStatus.MISS
    assert second.meta.source_mode == SourceMode.LIVE


@pytest.mark.asyncio
async def test_reference_code_fetches_real_source_files_when_available(test_config, store) -> None:
    # get_code_for_paper/search_code only ever returned repository metadata
    # (url/stars/license/topics), never actual file content, so the Code
    # Agent's reference_code was hardcoded to "" forever. Real .py source
    # files at the pinned commit must be fetched and take priority over the
    # README, which is documentation, not the algorithm.
    from rigor_rs.knowledge.models import CodeRecord, PaperIdentifiers, PaperRecord

    embeddings = FakeEmbeddings()

    class FakeGitHub:
        def __init__(self) -> None:
            self.readme_calls: list[str] = []
            self.listed_ref: str | None = None

        async def list_python_files(self, repository_url, ref, limit=2):
            self.listed_ref = ref
            return ["bpr/model.py", "bpr/train_test.py", "docs/example.py"]

        async def get_file_content(self, repository_url, path, ref):
            return f"class BPR(nn.Module):\n    def forward(self):\n        pass  # from {path}\n"

        async def get_readme(self, repository_url, ref=None):
            self.readme_calls.append(repository_url)
            return "# BPR reference implementation\n\nclass BPR(nn.Module): ...\n"

    github = FakeGitHub()
    ingestion = IngestionService(test_config, store, embeddings)
    budgets = BudgetManager(store, load_budget_config(test_config.budget_config).mcp)
    cache = QueryCache(store, test_config.retrieval.cache_ttl_seconds)
    retrieval = RetrievalService(test_config, store, embeddings, budgets, cache, ingestion, github=github)

    paper = PaperRecord(
        paper_id="arxiv:test-bpr", title="Test BPR", authors=["A"], year=2012, venue=None,
        abstract=None, identifiers=PaperIdentifiers(), paper_url=None, license="MIT",
        retracted=False, trust_tier="curated", content_completeness="metadata_only",
        priority_areas=["ranking_loss_alignment"], relevance_notes="pairwise ranking",
        keywords=[], sanitizer_flags=[], quarantined=False, content_hash="a" * 64,
        retrieved_at="2026-01-01T00:00:00+00:00",
        code=[CodeRecord(
            repository_url="https://github.com/example/bpr", pinned_commit="deadbeef",
            license="MIT", stars=10, paper_id="arxiv:test-bpr",
            retrieved_at="2026-01-01T00:00:00+00:00", content_hash="b" * 64, verified=True,
        )],
    )
    store.upsert_paper(paper, None, None, None, None)

    text, repositories = await retrieval.reference_code_for_experiment(
        ["arxiv:test-bpr"], "fallback query that must not be used",
    )

    assert github.listed_ref == "deadbeef"
    assert repositories == ["https://github.com/example/bpr"]
    assert "class BPR(nn.Module)" in text
    assert "from bpr/model.py" in text
    assert github.readme_calls == []  # real source files found -- README never needed


@pytest.mark.asyncio
async def test_reference_code_falls_back_to_readme_when_no_source_files_found(test_config, store) -> None:
    from rigor_rs.knowledge.models import CodeRecord, PaperIdentifiers, PaperRecord

    embeddings = FakeEmbeddings()

    class FakeGitHub:
        def __init__(self) -> None:
            self.readme_calls: list[str] = []

        async def list_python_files(self, repository_url, ref, limit=2):
            return []  # e.g. a non-Python repo, or the Git Trees API found nothing

        async def get_readme(self, repository_url, ref=None):
            self.readme_calls.append(repository_url)
            return "# BPR reference implementation\n\nclass BPR(nn.Module): ...\n"

    github = FakeGitHub()
    ingestion = IngestionService(test_config, store, embeddings)
    budgets = BudgetManager(store, load_budget_config(test_config.budget_config).mcp)
    cache = QueryCache(store, test_config.retrieval.cache_ttl_seconds)
    retrieval = RetrievalService(test_config, store, embeddings, budgets, cache, ingestion, github=github)

    paper = PaperRecord(
        paper_id="arxiv:test-bpr", title="Test BPR", authors=["A"], year=2012, venue=None,
        abstract=None, identifiers=PaperIdentifiers(), paper_url=None, license="MIT",
        retracted=False, trust_tier="curated", content_completeness="metadata_only",
        priority_areas=["ranking_loss_alignment"], relevance_notes="pairwise ranking",
        keywords=[], sanitizer_flags=[], quarantined=False, content_hash="a" * 64,
        retrieved_at="2026-01-01T00:00:00+00:00",
        code=[CodeRecord(
            repository_url="https://github.com/example/bpr", pinned_commit="deadbeef",
            license="MIT", stars=10, paper_id="arxiv:test-bpr",
            retrieved_at="2026-01-01T00:00:00+00:00", content_hash="b" * 64, verified=True,
        )],
    )
    store.upsert_paper(paper, None, None, None, None)

    text, repositories = await retrieval.reference_code_for_experiment(
        ["arxiv:test-bpr"], "fallback query that must not be used",
    )

    assert github.readme_calls == ["https://github.com/example/bpr"]
    assert repositories == ["https://github.com/example/bpr"]
    assert "class BPR(nn.Module)" in text
    assert "https://github.com/example/bpr" in text


@pytest.mark.asyncio
async def test_reference_code_degrades_to_empty_on_any_failure(test_config, store) -> None:
    embeddings = FakeEmbeddings()

    class ExplodingGitHub:
        async def get_readme(self, repository_url, ref=None):
            raise RuntimeError("GitHub is down")

        async def search_code_records(self, query, language, min_stars, limit):
            raise RuntimeError("GitHub is down")

    ingestion = IngestionService(test_config, store, embeddings)
    budgets = BudgetManager(store, load_budget_config(test_config.budget_config).mcp)
    cache = QueryCache(store, test_config.retrieval.cache_ttl_seconds)
    retrieval = RetrievalService(test_config, store, embeddings, budgets, cache, ingestion, github=ExplodingGitHub())

    text, repositories = await retrieval.reference_code_for_experiment(
        ["arxiv:does-not-exist"], "some query",
    )

    assert text == ""
    assert repositories == []
