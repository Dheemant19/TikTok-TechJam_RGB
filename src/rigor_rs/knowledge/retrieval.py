from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date

import numpy as np

from rigor_rs.knowledge.budgets import BudgetExceeded, BudgetManager
from rigor_rs.knowledge.cache import QueryCache, canonical_cache_key, normalize_query
from rigor_rs.knowledge.config import KnowledgeConfig
from rigor_rs.knowledge.embeddings import EmbeddingProvider, vector_from_bytes
from rigor_rs.knowledge.ingestion import IngestionService
from rigor_rs.knowledge.models import (
    CacheStatus, CitationExpansionResult, CitationRecord, CodeForPaperResult, CodeSearchResult,
    EvidenceFilters, EvidenceMatch, EvidenceSearchResult, FullTextResult, PaperRecord,
    Provenance, ResearchCard, ResponseMeta, SourceMode, ToolError,
)
from rigor_rs.knowledge.providers.github import GitHubProvider
from rigor_rs.knowledge.providers.openalex import OpenAlexProvider
from rigor_rs.knowledge.store import KnowledgeStore


class RetrievalService:
    def __init__(
        self, config: KnowledgeConfig, store: KnowledgeStore, embeddings: EmbeddingProvider,
        budgets: BudgetManager, cache: QueryCache, ingestion: IngestionService,
        openalex: OpenAlexProvider | None = None, github: GitHubProvider | None = None,
        session_id: str = "standalone", experiment_id: str = "standalone",
    ) -> None:
        self.config = config
        self.store = store
        self.embeddings = embeddings
        self.budgets = budgets
        self.cache = cache
        self.ingestion = ingestion
        self.openalex = openalex
        self.github = github
        self.session_id = session_id
        self.experiment_id = experiment_id

    @staticmethod
    def request_id() -> str:
        return f"req-{uuid.uuid4().hex}"

    @staticmethod
    def provenance(paper: PaperRecord) -> Provenance:
        return Provenance(
            source=paper.trust_tier, source_url=paper.paper_url, retrieved_at=paper.retrieved_at,
            content_hash=paper.content_hash, license=paper.license, trust_tier=paper.trust_tier,
        )

    def _meta(
        self, request_id: str, cache_status: CacheStatus, source_mode: SourceMode,
        papers: list[PaperRecord], warnings: list[str] | None = None, error: ToolError | None = None,
        session_id: str | None = None, experiment_id: str | None = None,
    ) -> ResponseMeta:
        return ResponseMeta(
            request_id=request_id, cache_status=cache_status, source_mode=source_mode,
            selected_record_ids=[paper.paper_id for paper in papers],
            provenance=[self.provenance(paper) for paper in papers],
            cap_usage=self.budgets.usage(session_id or self.session_id, experiment_id or self.experiment_id),
            warnings=warnings or [], error=error,
        )

    @staticmethod
    def _passes(paper: PaperRecord, filters: EvidenceFilters | None) -> bool:
        if paper.retracted or paper.quarantined:
            return False
        if filters is None:
            return True
        if filters.year_from and (paper.year is None or paper.year < filters.year_from):
            return False
        if filters.year_to and (paper.year is None or paper.year > filters.year_to):
            return False
        if filters.venue and (not paper.venue or filters.venue.casefold() not in paper.venue.casefold()):
            return False
        if filters.priority_area and filters.priority_area not in paper.priority_areas:
            return False
        if filters.trust_tier and paper.trust_tier != filters.trust_tier:
            return False
        if filters.require_license and not paper.license:
            return False
        if filters.require_code and not paper.code:
            return False
        return True

    _STOPWORDS = frozenset({
        "a", "an", "the", "of", "for", "with", "and", "or", "to", "in", "on", "is",
        "are", "be", "by", "as", "that", "this", "it", "at", "from", "into", "than",
    })

    @classmethod
    def _content_terms(cls, text: str) -> set[str]:
        return {term for term in normalize_query(text).replace("-", " ").split() if term and term not in cls._STOPWORDS}

    @staticmethod
    def _paper_text(paper: PaperRecord) -> str:
        return " ".join(filter(None, [
            paper.title, paper.abstract, " ".join(paper.keywords),
            " ".join(paper.priority_areas), paper.relevance_notes,
        ])).casefold().replace("-", " ")

    def _local_matches(self, query: str, semantic: bool, filters: EvidenceFilters | None, limit: int) -> list[EvidenceMatch]:
        fetch_limit = max(limit * 4, 20)
        keyword = self.store.search_fts(query, fetch_limit)
        semantic_rows: list[tuple[str, float]] = []
        if semantic:
            query_vector = self.embeddings.embed([query])[0]
            norm = float(np.linalg.norm(query_vector))
            for paper_id, dimension, raw in self.store.vector_rows():
                vector = vector_from_bytes(raw, dimension)
                denominator = norm * float(np.linalg.norm(vector))
                similarity = float(np.dot(query_vector, vector) / denominator) if denominator else 0.0
                if similarity >= 0.15:
                    semantic_rows.append((paper_id, similarity))
            semantic_rows.sort(key=lambda item: (-item[1], item[0]))
            semantic_rows = semantic_rows[:fetch_limit]
        rrf_constant = self.config.retrieval.reciprocal_rank_constant
        scores: dict[str, float] = {}
        reasons: dict[str, list[str]] = {}
        for rank, (paper_id, _) in enumerate(keyword, 1):
            scores[paper_id] = scores.get(paper_id, 0.0) + 1.0 / (rrf_constant + rank)
            reasons.setdefault(paper_id, []).append("exact terms")
        for rank, (paper_id, similarity) in enumerate(semantic_rows, 1):
            scores[paper_id] = scores.get(paper_id, 0.0) + 1.0 / (rrf_constant + rank)
            reasons.setdefault(paper_id, []).append(f"semantic similarity {similarity:.3f}")
        query_terms = self._content_terms(query)
        semantic_paper_ids = {paper_id for paper_id, _ in semantic_rows}
        matches: list[EvidenceMatch] = []
        for paper_id, score in scores.items():
            paper = self.store.get_paper(paper_id)
            if not paper or not self._passes(paper, filters):
                continue
            # A keyword candidate must actually cover a meaningful fraction of the
            # query's real content words, not just any single common word — e.g. an
            # 8-word query matching only on "learning" should not count as relevant.
            # Semantic candidates already passed a real similarity threshold above.
            paper_text = self._paper_text(paper)
            overlap = len(query_terms & self._content_terms(paper_text)) / len(query_terms) if query_terms else 0.0
            keyword_relevant = overlap >= 0.5
            if not keyword_relevant and paper_id not in semantic_paper_ids:
                continue
            if normalize_query(query) in paper_text:
                reasons[paper_id].append("curated note")
            matches.append(EvidenceMatch(paper=paper, score=score, match_reasons=reasons[paper_id]))
        matches.sort(key=lambda item: (-item.score, item.paper.trust_tier != "curated", item.paper.paper_id))
        return matches[:limit]

    async def search_evidence(
        self, query: str, semantic: bool = True, filters: EvidenceFilters | None = None,
        max_results: int = 8, session_id: str | None = None, experiment_id: str | None = None,
    ) -> EvidenceSearchResult:
        sid, eid = session_id or self.session_id, experiment_id or self.experiment_id
        if not query.strip() or max_results < 1 or max_results > self.config.retrieval.maximum_search_results:
            request_id = self.request_id()
            error = ToolError(code="invalid_request", message="query and max_results are outside configured limits")
            return EvidenceSearchResult(meta=self._meta(request_id, CacheStatus.BYPASS, SourceMode.LOCAL, [], error=error, session_id=sid, experiment_id=eid), results=[])
        request_id = self.request_id()
        key, canonical_request = canonical_cache_key("hybrid", query, filters, date.today(), max_results)
        cached = self.cache.get(key)
        if cached:
            results = []
            for item in cached.get("results", []):
                paper = self.store.get_paper(item["paper_id"])
                if paper and self._passes(paper, filters):
                    results.append(EvidenceMatch(paper=paper, score=item["score"], match_reasons=item["match_reasons"]))
            characters = len(json.dumps(cached, ensure_ascii=False))
            try:
                self.budgets.consume(
                    session_id=sid, experiment_id=eid, provider="cache", request_id=request_id,
                    documents=len(results), characters=characters,
                )
            except BudgetExceeded as error:
                tool_error = ToolError(code="budget_exhausted", message=str(error))
                return EvidenceSearchResult(meta=self._meta(request_id, CacheStatus.HIT, SourceMode.CACHE, [], error=tool_error, session_id=sid, experiment_id=eid), results=[])
            papers = [item.paper for item in results]
            return EvidenceSearchResult(meta=self._meta(request_id, CacheStatus.HIT, SourceMode.CACHE, papers, session_id=sid, experiment_id=eid), results=results)
        matches = self._local_matches(query, semantic, filters, max_results)
        source_mode = SourceMode.LOCAL
        warnings: list[str] = []
        tool_error: ToolError | None = None
        # Always attempt a live OpenAlex fetch when configured, not only when the local
        # corpus is empty. The curated bank is a helpful prior, not an exclusive source:
        # a live paper can be more relevant or more recent than anything curated. The
        # live records are ingested into the same store, then local search reruns over
        # the updated corpus so curated and newly-discovered evidence rank together via
        # the same reciprocal-rank-fusion scoring, instead of being treated as separate,
        # mutually-exclusive result sets.
        if self.openalex:
            try:
                self.budgets.ensure_outbound_available(sid, eid)
                provider_result = await self.openalex.search(query, filters, max_results)
                self.budgets.consume(
                    session_id=sid, experiment_id=eid, provider="openalex", request_id=request_id,
                    outbound=provider_result.attempts, documents=len(provider_result.records),
                    retries=max(0, provider_result.attempts - 1), errors=int(provider_result.error is not None),
                )
                if provider_result.error:
                    warnings.append(provider_result.error_message or "OpenAlex unavailable")
                    source_mode = SourceMode.LOCAL_FALLBACK
                else:
                    await self.ingestion.enqueue_provider_records(provider_result.records, query)
                    await self.ingestion.process_queue(resolve_code=False)
                    matches = self._local_matches(query, semantic, filters, max_results)
                    source_mode = SourceMode.LIVE
            except BudgetExceeded as error:
                # A live fetch may already have succeeded before this budget check ran;
                # `matches` still reflects whatever the local corpus already had, but the
                # caller must see a real budget_exhausted error, not a fake local success.
                tool_error = ToolError(code="budget_exhausted", message=str(error))
                warnings.append(str(error))
                source_mode = SourceMode.LOCAL_FALLBACK
        # Never cache a failed/budget-exhausted fetch, or a genuine zero-match result:
        # doing so would permanently serve an empty result for up to cache_ttl_seconds
        # even after the corpus grows via ingestion or the provider recovers.
        if tool_error is None and matches:
            cache_payload = {"results": [
                {"paper_id": item.paper.paper_id, "score": item.score, "match_reasons": item.match_reasons}
                for item in matches
            ]}
            self.cache.put(key, "hybrid", canonical_request, cache_payload)
        characters = len(json.dumps([
            {"paper_id": item.paper.paper_id, "score": item.score, "match_reasons": item.match_reasons}
            for item in matches
        ], ensure_ascii=False))
        try:
            self.budgets.consume(
                session_id=sid, experiment_id=eid, provider="local", request_id=request_id,
                documents=len(matches), characters=characters,
            )
        except BudgetExceeded as error:
            tool_error = ToolError(code="budget_exhausted", message=str(error))
            return EvidenceSearchResult(meta=self._meta(request_id, CacheStatus.MISS, source_mode, [], warnings, tool_error, session_id=sid, experiment_id=eid), results=[])
        papers = [item.paper for item in matches]
        return EvidenceSearchResult(meta=self._meta(request_id, CacheStatus.MISS, source_mode, papers, warnings, tool_error, session_id=sid, experiment_id=eid), results=matches)

    async def get_paper_result(self, paper_id: str) -> tuple[ResponseMeta, PaperRecord | None]:
        request_id = self.request_id()
        paper = self.store.get_paper(paper_id)
        if paper is None:
            return self._meta(request_id, CacheStatus.BYPASS, SourceMode.LOCAL, [], error=ToolError(code="not_found", message="paper not found")), None
        if paper.quarantined:
            return self._meta(request_id, CacheStatus.BYPASS, SourceMode.LOCAL, [paper], error=ToolError(code="quarantined", message="paper text is quarantined")), paper
        return self._meta(request_id, CacheStatus.BYPASS, SourceMode.LOCAL, [paper]), paper

    async def get_fulltext(self, paper_id: str) -> FullTextResult:
        meta, paper = await self.get_paper_result(paper_id)
        return FullTextResult(
            meta=meta, paper_id=paper_id, available=False, fulltext=None,
            lawful_source_url=paper.paper_url if paper else None,
        )

    async def search_code(self, query: str, language: str = "Python", min_stars: int = 0, max_results: int = 5) -> CodeSearchResult:
        request_id = self.request_id()
        if max_results < 1 or max_results > self.config.retrieval.maximum_code_results:
            return CodeSearchResult(meta=self._meta(request_id, CacheStatus.BYPASS, SourceMode.LOCAL, [], error=ToolError(code="invalid_request", message="max_results outside configured limit")), results=[])
        discovered = self.store.code_search(query, language, min_stars, max_results)
        local = [item for item in discovered if item.verified]
        source_mode = SourceMode.LOCAL
        warnings: list[str] = []
        if discovered and not local:
            warnings.append("Unpinned or unlicensed repositories were withheld")
        tool_error: ToolError | None = None
        if not local and self.github:
            usage = self.budgets.usage(self.session_id, self.experiment_id)
            remaining_requests = min(
                self.budgets.config.per_session.outbound_provider_requests - usage.session_provider_requests,
                self.budgets.config.per_experiment.outbound_provider_requests - usage.experiment_provider_requests,
            )
            # GitHub costs 1 request to search plus 2 requests per resolved repository
            # (metadata + pinned commit). Bound the resolve count up front so we never
            # fetch repositories we cannot afford to keep, then silently discard them.
            resolvable = min(max_results, max(0, (remaining_requests - 1) // 2)) if remaining_requests >= 3 else 0
            if resolvable == 0:
                tool_error = ToolError(code="budget_exhausted", message="not enough remaining provider-request budget to search GitHub")
                source_mode = SourceMode.LOCAL_FALLBACK
            else:
                try:
                    local, attempts = await self.github.search_code_records(query, language, min_stars, resolvable)
                    self.budgets.consume(
                        session_id=self.session_id, experiment_id=self.experiment_id, provider="github", request_id=request_id,
                        outbound=attempts, documents=len(local), retries=max(0, attempts - 1),
                    )
                    source_mode = SourceMode.LIVE
                    if resolvable < max_results:
                        warnings.append(f"Only {resolvable} of {max_results} requested repositories were searched due to remaining budget")
                except BudgetExceeded as error:
                    tool_error = ToolError(code="budget_exhausted", message=str(error))
                    source_mode = SourceMode.LOCAL_FALLBACK
                    local = []
                except Exception as error:
                    tool_error = ToolError(code="transient_failure", message=str(error))
                    warnings.append(str(error))
                    source_mode = SourceMode.LOCAL_FALLBACK
                    local = []
        characters = len(json.dumps([item.model_dump(mode="json") for item in local], ensure_ascii=False))
        try:
            self.budgets.consume(
                session_id=self.session_id, experiment_id=self.experiment_id, provider="local", request_id=request_id,
                documents=len(local), characters=characters,
            )
        except BudgetExceeded as error:
            return CodeSearchResult(meta=self._meta(request_id, CacheStatus.MISS, source_mode, [], warnings, ToolError(code="budget_exhausted", message=str(error))), results=[])
        return CodeSearchResult(meta=ResponseMeta(
            request_id=request_id, cache_status=CacheStatus.MISS, source_mode=source_mode,
            selected_record_ids=[item.repository_url for item in local], provenance=[],
            cap_usage=self.budgets.usage(self.session_id, self.experiment_id), warnings=warnings, error=tool_error,
        ), results=local)

    async def get_code_for_paper(self, paper_id: str) -> CodeForPaperResult:
        request_id = self.request_id()
        paper = self.store.get_paper(paper_id)
        if not paper:
            return CodeForPaperResult(meta=self._meta(request_id, CacheStatus.BYPASS, SourceMode.LOCAL, [], error=ToolError(code="not_found", message="paper not found")), paper_id=paper_id, results=[])
        verified = [item for item in paper.code if item.verified]
        warnings = [] if len(verified) == len(paper.code) else ["Unpinned or unlicensed repositories were withheld"]
        return CodeForPaperResult(meta=self._meta(request_id, CacheStatus.BYPASS, SourceMode.LOCAL, [paper], warnings), paper_id=paper_id, results=verified)

    async def expand_citations(self, work_id: str, direction: str, max_results: int = 10) -> CitationExpansionResult:
        request_id = self.request_id()
        citations = self.store.citations(work_id, direction, max_results)
        source_mode = SourceMode.LOCAL
        warnings: list[str] = []
        tool_error: ToolError | None = None
        if not citations and self.openalex:
            try:
                self.budgets.ensure_outbound_available(self.session_id, self.experiment_id)
                result = await self.openalex.get_citations(work_id, direction, max_results)
                self.budgets.consume(
                    session_id=self.session_id, experiment_id=self.experiment_id, provider="openalex", request_id=request_id,
                    outbound=result.attempts, documents=len(result.records), retries=max(0, result.attempts - 1),
                    errors=int(result.error is not None),
                )
                if result.error:
                    warnings.append(result.error_message or "citation provider unavailable")
                    source_mode = SourceMode.LOCAL_FALLBACK
                else:
                    for record in result.records:
                        citation = CitationRecord(
                            source_paper_id=work_id if direction == "cites" else record.paper_id,
                            target_paper_id=record.paper_id if direction == "cites" else work_id,
                            relation=direction, provider="openalex",
                        )
                        self.store.add_citation(citation)
                        citations.append(citation)
                    source_mode = SourceMode.LIVE
            except BudgetExceeded as error:
                tool_error = ToolError(code="budget_exhausted", message=str(error))
                warnings.append(str(error))
                source_mode = SourceMode.LOCAL_FALLBACK
        # The "selected" records are the citing/cited papers actually discovered, not
        # the constant input work_id (which sits on the fixed side of every edge).
        limited_citations = citations[:max_results]
        discovered_ids = [
            item.source_paper_id if direction == "cited_by" else item.target_paper_id
            for item in limited_citations
        ]
        return CitationExpansionResult(meta=ResponseMeta(
            request_id=request_id, cache_status=CacheStatus.MISS, source_mode=source_mode,
            selected_record_ids=discovered_ids, provenance=[],
            cap_usage=self.budgets.usage(self.session_id, self.experiment_id), warnings=warnings, error=tool_error,
        ), work_id=work_id, direction=direction, citations=limited_citations)

    async def research_card(
        self, hypothesis: str, max_evidence: int = 6,
        session_id: str | None = None, experiment_id: str | None = None,
    ) -> ResearchCard:
        search = await self.search_evidence(
            hypothesis, True, None, max_evidence, session_id=session_id, experiment_id=experiment_id,
        )
        contradiction_terms = ("regression", "conflict", "bias", "limitation", "negative", "fails")
        contradicting = [item for item in search.results if any(term in item.paper.relevance_notes.casefold() for term in contradiction_terms)]
        supporting = [item for item in search.results if item not in contradicting]
        missing = [] if len(search.results) >= max_evidence else [f"Only {len(search.results)} relevant evidence records were available"]
        return ResearchCard(
            meta=search.meta, hypothesis=hypothesis, supporting=supporting,
            contradicting=contradicting, missing_evidence=missing,
            source_ids=[item.paper.paper_id for item in search.results],
        )
