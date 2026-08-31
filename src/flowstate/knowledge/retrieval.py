from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date

import numpy as np

from flowstate.knowledge.budgets import BudgetExceeded, BudgetManager
from flowstate.knowledge.cache import QueryCache, canonical_cache_key, normalize_query
from flowstate.knowledge.config import KnowledgeConfig
from flowstate.knowledge.embeddings import EmbeddingProvider, vector_from_bytes
from flowstate.knowledge.ingestion import IngestionService
from flowstate.knowledge.models import (
    CacheStatus, CitationExpansionResult, CodeForPaperResult, CodeRecord, CodeSearchResult,
    EvidenceFilters, EvidenceMatch, EvidenceSearchResult, FullTextResult, PaperRecord,
    Provenance, ResearchCard, ResponseMeta, SourceMode, ToolError,
)
from flowstate.knowledge.providers.github import GitHubProvider
from flowstate.knowledge.providers.huggingface_papers import HuggingFacePapersProvider
from flowstate.knowledge.store import KnowledgeStore


class RetrievalService:
    def __init__(
        self, config: KnowledgeConfig, store: KnowledgeStore, embeddings: EmbeddingProvider,
        budgets: BudgetManager, cache: QueryCache, ingestion: IngestionService,
        huggingface: HuggingFacePapersProvider | None = None, github: GitHubProvider | None = None,
        session_id: str = "standalone", experiment_id: str = "standalone",
    ) -> None:
        self.config = config
        self.store = store
        self.embeddings = embeddings
        self.budgets = budgets
        self.cache = cache
        self.ingestion = ingestion
        self.huggingface = huggingface
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
        if filters.require_code and not any(code.verified for code in paper.code):
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

    def _balance_sources(self, matches: list[EvidenceMatch], limit: int) -> list[EvidenceMatch]:
        """Reserve evidence slots by source, then interleave both ranked pools.

        `curated_bank_share=0.5` yields three curated and three discovered
        papers for a six-item card when both sources have enough relevant
        results. If either source is short, the other fills the unused slots.
        """
        curated_target = int(limit * self.config.retrieval.curated_bank_share + 0.5)
        discovered_target = limit - curated_target
        curated = [item for item in matches if item.paper.trust_tier == "curated"][:curated_target]
        discovered = [item for item in matches if item.paper.trust_tier != "curated"][:discovered_target]
        selected: list[EvidenceMatch] = []
        curated_index = 0
        discovered_index = 0
        scheduled = len(curated) + len(discovered)
        for position in range(1, scheduled + 1):
            desired_curated = min(
                len(curated),
                int(position * self.config.retrieval.curated_bank_share + 0.5),
            )
            if curated_index < desired_curated or discovered_index >= len(discovered):
                selected.append(curated[curated_index])
                curated_index += 1
            elif discovered_index < len(discovered):
                selected.append(discovered[discovered_index])
                discovered_index += 1
        selected_ids = {item.paper.paper_id for item in selected}
        selected.extend(
            item for item in matches
            if item.paper.paper_id not in selected_ids
        )
        return selected[:limit]

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
        matches.sort(key=lambda item: (-item.score, item.paper.paper_id))
        return self._balance_sources(matches, limit)

    async def search_evidence(
        self, query: str, semantic: bool = True, filters: EvidenceFilters | None = None,
        max_results: int = 8, session_id: str | None = None, experiment_id: str | None = None,
        bypass_cache: bool = False,
    ) -> EvidenceSearchResult:
        sid, eid = session_id or self.session_id, experiment_id or self.experiment_id
        if not query.strip() or max_results < 1 or max_results > self.config.retrieval.maximum_search_results:
            request_id = self.request_id()
            error = ToolError(code="invalid_request", message="query and max_results are outside configured limits")
            return EvidenceSearchResult(meta=self._meta(request_id, CacheStatus.BYPASS, SourceMode.LOCAL, [], error=error, session_id=sid, experiment_id=eid), results=[])
        request_id = self.request_id()
        balance_key = f"hybrid-balanced-{self.config.retrieval.curated_bank_share:.6f}"
        key, canonical_request = canonical_cache_key(balance_key, query, filters, date.today(), max_results)
        cached = None if bypass_cache else self.cache.get(key)
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
        # Reserve the configured share of the evidence card for fresh,
        # code-linked Hugging Face discoveries. For a six-paper card and
        # curated_bank_share=0.5 this asks for three live candidates, then
        # `_balance_sources` interleaves three curated and three discovered
        # records. If either source has fewer relevant, verified results, the
        # other source fills the card rather than returning artificial gaps.
        curated_target = int(max_results * self.config.retrieval.curated_bank_share + 0.5)
        discovered_target = max_results - curated_target
        if self.huggingface and discovered_target:
            try:
                self.budgets.ensure_outbound_available(sid, eid)
                provider_result = await self.huggingface.search(
                    query, filters, discovered_target, session_id=sid
                )
                self.budgets.consume(
                    session_id=sid, experiment_id=eid, provider="huggingface_papers", request_id=request_id,
                    outbound=provider_result.attempts, documents=len(provider_result.records),
                    retries=max(0, provider_result.attempts - 1), errors=int(provider_result.error is not None),
                )
                if provider_result.error:
                    warnings.append(provider_result.error_message or "Hugging Face Papers unavailable")
                    source_mode = SourceMode.LOCAL_FALLBACK
                elif provider_result.records:
                    await self.ingestion.enqueue_provider_records(provider_result.records, query)
                    await self.ingestion.process_queue(resolve_code=True)
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

    async def search_code(
        self, query: str, language: str = "Python", min_stars: int = 0, max_results: int = 5,
        session_id: str | None = None, experiment_id: str | None = None,
    ) -> CodeSearchResult:
        request_id = self.request_id()
        active_session_id = session_id or self.session_id
        active_experiment_id = experiment_id or self.experiment_id
        if max_results < 1 or max_results > self.config.retrieval.maximum_code_results:
            return CodeSearchResult(meta=self._meta(
                request_id, CacheStatus.BYPASS, SourceMode.LOCAL, [],
                error=ToolError(code="invalid_request", message="max_results outside configured limit"),
                session_id=active_session_id, experiment_id=active_experiment_id,
            ), results=[])
        discovered = self.store.code_search(query, language, min_stars, max_results)
        local = [item for item in discovered if item.verified]
        source_mode = SourceMode.LOCAL
        warnings: list[str] = []
        if discovered and not local:
            warnings.append("Unpinned or unlicensed repositories were withheld")
        tool_error: ToolError | None = None
        if not local and self.github:
            usage = self.budgets.usage(active_session_id, active_experiment_id)
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
                        session_id=active_session_id, experiment_id=active_experiment_id,
                        provider="github", request_id=request_id,
                        outbound=attempts, documents=len(local), retries=max(0, attempts - 1),
                        errors=0,
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
                session_id=active_session_id, experiment_id=active_experiment_id,
                provider="local", request_id=request_id, documents=len(local), characters=characters,
            )
        except BudgetExceeded as error:
            return CodeSearchResult(meta=self._meta(
                request_id, CacheStatus.MISS, source_mode, [], warnings,
                ToolError(code="budget_exhausted", message=str(error)),
                session_id=active_session_id, experiment_id=active_experiment_id,
            ), results=[])
        return CodeSearchResult(meta=ResponseMeta(
            request_id=request_id, cache_status=CacheStatus.MISS, source_mode=source_mode,
            selected_record_ids=[item.repository_url for item in local], provenance=[],
            cap_usage=self.budgets.usage(active_session_id, active_experiment_id),
            warnings=warnings, error=tool_error,
        ), results=local)

    async def get_code_for_paper(self, paper_id: str) -> CodeForPaperResult:
        request_id = self.request_id()
        paper = self.store.get_paper(paper_id)
        if not paper:
            return CodeForPaperResult(meta=self._meta(request_id, CacheStatus.BYPASS, SourceMode.LOCAL, [], error=ToolError(code="not_found", message="paper not found")), paper_id=paper_id, results=[])
        verified = [item for item in paper.code if item.verified]
        warnings = [] if len(verified) == len(paper.code) else ["Unpinned or unlicensed repositories were withheld"]
        return CodeForPaperResult(meta=self._meta(request_id, CacheStatus.BYPASS, SourceMode.LOCAL, [paper], warnings), paper_id=paper_id, results=verified)

    async def discover_code_paper(
        self, query: str, session_id: str | None = None, experiment_id: str | None = None,
    ) -> CodeForPaperResult:
        """Fetch exactly one fresh, code-linked paper from Hugging Face Papers
        for `query` -- never a repeat of a paper already surfaced this
        session -- and return only its verified repository record. This is
        the MCP-exposed counterpart to the discovery path search_evidence()
        now uses internally on every research() call.
        """
        sid, eid = session_id or self.session_id, experiment_id or self.experiment_id
        request_id = self.request_id()
        if not self.huggingface:
            return CodeForPaperResult(meta=self._meta(
                request_id, CacheStatus.BYPASS, SourceMode.LOCAL, [],
                error=ToolError(code="provider_unavailable", message="Hugging Face Papers provider is disabled"),
                session_id=sid, experiment_id=eid,
            ), paper_id="", results=[])
        try:
            self.budgets.ensure_outbound_available(sid, eid)
            result = await self.huggingface.search(query, None, 1, session_id=sid)
            self.budgets.consume(
                session_id=sid, experiment_id=eid, provider="huggingface_papers", request_id=request_id,
                outbound=result.attempts, documents=len(result.records),
                retries=max(0, result.attempts - 1), errors=int(result.error is not None),
            )
        except BudgetExceeded as error:
            return CodeForPaperResult(meta=self._meta(
                request_id, CacheStatus.BYPASS, SourceMode.LOCAL, [],
                error=ToolError(code="budget_exhausted", message=str(error)),
                session_id=sid, experiment_id=eid,
            ), paper_id="", results=[])
        if result.error:
            return CodeForPaperResult(meta=self._meta(
                request_id, CacheStatus.MISS, SourceMode.LOCAL_FALLBACK, [],
                error=ToolError(code=result.error, message=result.error_message or "discovery failed"),
                session_id=sid, experiment_id=eid,
            ), paper_id="", results=[])
        # Hard check, defense in depth: HuggingFacePapersProvider.search()
        # already only ever returns a record with a linked repository, but a
        # provider boundary is never trusted twice.
        codeful = [record for record in result.records if record.github_repositories]
        if not codeful:
            return CodeForPaperResult(meta=self._meta(
                request_id, CacheStatus.MISS, SourceMode.LIVE, [],
                warnings=["No new code-linked paper was found for this query this session"],
                session_id=sid, experiment_id=eid,
            ), paper_id="", results=[])
        await self.ingestion.enqueue_provider_records(codeful, query)
        await self.ingestion.process_queue(resolve_code=True)
        return await self.get_code_for_paper(codeful[0].paper_id)

    async def reference_code_for_experiment(
        self, paper_ids: list[str], fallback_query: str,
        session_id: str | None = None, experiment_id: str | None = None,
        max_repositories: int = 2, max_files_per_repository: int = 2, max_characters: int = 20_000,
    ) -> tuple[str, list[str]]:
        """Assemble real reference-code text for the Code Agent. get_code_for_paper
        /search_code above only ever return a CodeRecord (repository_url, stars,
        license, topics) -- no file content -- so for each resolved repository
        this lists its Python source tree at the pinned commit and fetches the
        highest-ranked real implementation files (GitHubProvider.list_python_files
        + get_file_content); only when no .py files are found (or no commit is
        pinned) does it fall back to the repository's README. Cited papers'
        already-pinned, license-verified repositories are tried first (free,
        local); a live GitHub search on the experiment's primary_change is the
        fallback when no cited paper has one. Any failure (network, rate limit,
        budget) degrades to no reference code rather than blocking patch
        generation -- reference code is a helpful supplement, not a requirement,
        and is handed to the LLM as untrusted quoted context, never executed.
        """
        try:
            records: list[CodeRecord] = []
            for paper_id in paper_ids[:max_repositories]:
                result = await self.get_code_for_paper(paper_id)
                records.extend(result.results)
            if not records and self.github:
                search = await self.search_code(fallback_query, max_results=max_repositories, session_id=session_id, experiment_id=experiment_id)
                records = search.results
            sections: list[str] = []
            used_repositories: list[str] = []
            per_repo_budget = max(max_characters // max(len(records[:max_repositories]), 1), 1)
            for record in records[:max_repositories]:
                if not self.github:
                    break
                header = f"# Reference: {record.repository_url} (paper={record.paper_id or 'n/a'}, stars={record.stars}, license={record.license})\n"
                body = ""
                if record.pinned_commit:
                    paths = await self.github.list_python_files(record.repository_url, record.pinned_commit, limit=max_files_per_repository)
                    parts = []
                    for path in paths:
                        content = await self.github.get_file_content(record.repository_url, path, record.pinned_commit)
                        if content:
                            parts.append(f"## {path}\n{content}")
                    body = "\n\n".join(parts)
                if not body:
                    body = await self.github.get_readme(record.repository_url, record.pinned_commit) or ""
                if not body:
                    continue
                sections.append(header + body[:per_repo_budget])
                used_repositories.append(record.repository_url)
            text = "\n\n".join(sections)[:max_characters]
            return text, used_repositories
        except Exception:
            return "", []

    async def expand_citations(self, work_id: str, direction: str, max_results: int = 10) -> CitationExpansionResult:
        # No configured provider exposes a citation graph (Hugging Face
        # Papers is a search/discovery API, not a citation index), so this
        # is intentionally local-only: it reflects citation_edges already
        # recorded in the store rather than fetching more.
        request_id = self.request_id()
        citations = self.store.citations(work_id, direction, max_results)
        limited_citations = citations[:max_results]
        discovered_ids = [
            item.source_paper_id if direction == "cited_by" else item.target_paper_id
            for item in limited_citations
        ]
        return CitationExpansionResult(meta=ResponseMeta(
            request_id=request_id, cache_status=CacheStatus.MISS, source_mode=SourceMode.LOCAL,
            selected_record_ids=discovered_ids, provenance=[],
            cap_usage=self.budgets.usage(self.session_id, self.experiment_id), warnings=[], error=None,
        ), work_id=work_id, direction=direction, citations=limited_citations)

    async def research_card(
        self, hypothesis: str, max_evidence: int = 6,
        session_id: str | None = None, experiment_id: str | None = None,
        filters: EvidenceFilters | None = None, bypass_cache: bool = False,
    ) -> ResearchCard:
        search = await self.search_evidence(
            hypothesis, True, filters, max_evidence, session_id=session_id, experiment_id=experiment_id,
            bypass_cache=bypass_cache,
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
