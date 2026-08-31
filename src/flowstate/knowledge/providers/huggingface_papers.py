from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from flowstate.knowledge.models import EvidenceFilters, GitHubRepository, PaperIdentifiers, ProviderResult, ProviderWork
from flowstate.knowledge.providers.base import KnowledgeProvider, ProviderFailure, RetryingHTTPClient


class HuggingFacePapersProvider(KnowledgeProvider):
    """Discovers live papers via Hugging Face's public Papers API, hard-filtered
    to only those with an author- or community-linked GitHub repository.

    OpenAlex (the provider this replaces) never returns a repository link at
    all -- ProviderWork.github_repositories was permanently empty for every
    discovered paper, so a "discovered" paper could never satisfy a
    code-availability requirement no matter how it was filtered. Every record
    this provider returns instead carries a real repository straight from
    HF's own `paper.githubRepo` metadata field (the same signal
    https://huggingface.co/papers shows as a paper's "Code" link); a paper
    with no `githubRepo` is dropped here and never surfaced as a fallback.
    """

    name = "huggingface_papers"
    base_url = "https://huggingface.co/api/papers"
    # The API has no working pagination (`page`/`skip` are silently ignored).
    # Widen the single ranked page until it contains the requested number of
    # fresh, code-linked papers, capped at 40 results per request.
    _ESCALATING_PAGE_SIZES = (1, 5, 15, 40)

    def __init__(self, *, timeout_seconds: float, retry_limit: int, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=timeout_seconds, headers={"User-Agent": "FlowState/0.1"})
        self.http = RetryingHTTPClient(self.client, retry_limit)
        # Per-session set of already-surfaced huggingface: paper_ids. A
        # KnowledgeRuntime (and this provider) is constructed once per
        # workflow session process, so in-memory tracking keyed by
        # session_id is sufficient and never needs to survive a restart.
        self._seen_by_session: dict[str, set[str]] = {}

    @staticmethod
    def _repository_url(entry: dict[str, Any]) -> str | None:
        paper = entry.get("paper") or entry
        repo = paper.get("githubRepo") or entry.get("githubRepo")
        return repo if isinstance(repo, str) and repo.startswith("https://github.com/") else None

    @staticmethod
    def _year(published_at: Any) -> int | None:
        if not isinstance(published_at, str):
            return None
        try:
            return datetime.fromisoformat(published_at.replace("Z", "+00:00")).year
        except ValueError:
            return None

    def _normalize(self, entry: dict[str, Any], repository_url: str, response_hash: str) -> ProviderWork:
        paper = entry.get("paper") or entry
        arxiv_id = str(paper.get("id") or entry.get("id"))
        authors = [author.get("name") for author in paper.get("authors", []) if author.get("name")]
        return ProviderWork(
            paper_id=f"huggingface:{arxiv_id}",
            title=paper.get("title") or "Untitled work",
            authors=authors,
            year=self._year(paper.get("publishedAt")),
            abstract=paper.get("summary"),
            identifiers=PaperIdentifiers(arxiv_id=arxiv_id),
            paper_url=f"https://huggingface.co/papers/{arxiv_id}",
            source=self.name, source_url=f"https://huggingface.co/papers/{arxiv_id}",
            raw_response_hash=response_hash,
            github_repositories=[GitHubRepository(url=repository_url)],
        )

    async def search(
        self, query: str, filters: EvidenceFilters | None, limit: int, *, session_id: str = "standalone",
    ) -> ProviderResult:
        seen = self._seen_by_session.setdefault(session_id, set())
        requested = max(1, min(limit, self._ESCALATING_PAGE_SIZES[-1]))
        page_sizes = tuple(dict.fromkeys(
            min(self._ESCALATING_PAGE_SIZES[-1], max(requested, size))
            for size in self._ESCALATING_PAGE_SIZES
        ))
        attempts = 0
        best: list[ProviderWork] = []
        for page_size in page_sizes:
            try:
                response = await self.http.get_json(
                    f"{self.base_url}/search",
                    params={"q": query, "limit": page_size},
                )
            except ProviderFailure as error:
                if best:
                    break
                return ProviderResult(
                    attempts=attempts + error.attempts,
                    error="transient_failure" if error.transient else "invalid_request",
                    error_message=str(error),
                )
            attempts += response.attempts
            entries = response.data if isinstance(response.data, list) else []
            candidates: list[ProviderWork] = []
            for entry in entries:
                paper = entry.get("paper") or entry
                arxiv_id = paper.get("id") or entry.get("id")
                if not arxiv_id:
                    continue
                paper_id = f"huggingface:{arxiv_id}"
                if paper_id in seen:
                    continue
                repository_url = self._repository_url(entry)
                if not repository_url:
                    continue
                candidates.append(self._normalize(entry, repository_url, response.response_hash))
                if len(candidates) == requested:
                    break
            if len(candidates) >= len(best):
                best = candidates
            if len(best) == requested:
                break
        for record in best:
            seen.add(record.paper_id)
        return ProviderResult(records=best, attempts=attempts)

    async def get_work(self, identifier: str) -> ProviderWork | None:
        try:
            response = await self.http.get_json(f"{self.base_url}/{identifier}")
        except ProviderFailure as error:
            if error.status_code == 404:
                return None
            raise
        entry = response.data if isinstance(response.data, dict) else {}
        arxiv_id = entry.get("id")
        if not arxiv_id:
            return None
        repository_url = self._repository_url({"paper": entry})
        return ProviderWork(
            paper_id=f"huggingface:{arxiv_id}",
            title=entry.get("title") or "Untitled work",
            authors=[author.get("name") for author in entry.get("authors", []) if author.get("name")],
            year=self._year(entry.get("publishedAt")),
            abstract=entry.get("summary"),
            identifiers=PaperIdentifiers(arxiv_id=str(arxiv_id)),
            paper_url=f"https://huggingface.co/papers/{arxiv_id}",
            source=self.name, source_url=f"https://huggingface.co/papers/{arxiv_id}",
            raw_response_hash=response.response_hash,
            github_repositories=[GitHubRepository(url=repository_url)] if repository_url else [],
        )

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()
