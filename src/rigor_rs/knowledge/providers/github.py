from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from rigor_rs.knowledge.models import CodeRecord, EvidenceFilters, ProviderResult, ProviderWork
from rigor_rs.knowledge.providers.base import KnowledgeProvider, ProviderFailure, RetryingHTTPClient


class GitHubProvider(KnowledgeProvider):
    name = "github"
    base_url = "https://api.github.com"

    def __init__(self, *, token: str | None, timeout_seconds: float, retry_limit: int, client: httpx.AsyncClient | None = None) -> None:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "RIGOR-RS/0.1"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._owns_client = client is None
        # GitHub 301s renamed/moved repositories (e.g. after a rename) with a body
        # containing only {message, url, documentation_url} — no repo fields at all.
        # Following redirects resolves to the real, current repo metadata instead.
        self.client = client or httpx.AsyncClient(timeout=timeout_seconds, headers=headers, follow_redirects=True)
        self.http = RetryingHTTPClient(self.client, retry_limit)

    async def search(self, query: str, filters: EvidenceFilters | None, limit: int) -> ProviderResult:
        try:
            response = await self.http.get_json(
                f"{self.base_url}/search/repositories", params={"q": query, "per_page": limit, "sort": "stars"}
            )
        except ProviderFailure as error:
            return ProviderResult(
                attempts=error.attempts, error="transient_failure" if error.transient else "invalid_request",
                error_message=str(error),
            )
        records = []
        for item in response.data.get("items", []):
            full_name = item.get("full_name")
            if not full_name:
                continue
            records.append(ProviderWork(
                paper_id=f"github:{full_name.casefold().replace('/', '-')}", title=full_name,
                abstract=item.get("description"), paper_url=item.get("html_url"), license=(item.get("license") or {}).get("spdx_id"),
                source=self.name, source_url=item.get("html_url"), raw_response_hash=response.response_hash,
            ))
        return ProviderResult(records=records, attempts=response.attempts)

    async def get_work(self, identifier: str) -> ProviderWork | None:
        repository = identifier.removeprefix("https://github.com/").strip("/")
        try:
            response = await self.http.get_json(f"{self.base_url}/repos/{quote(repository, safe='/')}")
        except ProviderFailure as error:
            if error.status_code == 404:
                return None
            raise
        item = response.data
        full_name = item.get("full_name")
        if not full_name:
            # Defense in depth even with redirects enabled: an unexpected response
            # shape (e.g. a still-unresolved API quirk) degrades to "not found" rather
            # than crashing the caller with a raw KeyError.
            return None
        return ProviderWork(
            paper_id=f"github:{full_name.casefold().replace('/', '-')}", title=full_name,
            abstract=item.get("description"), paper_url=item.get("html_url"), license=(item.get("license") or {}).get("spdx_id"),
            source=self.name, source_url=item.get("html_url"), raw_response_hash=response.response_hash,
        )

    async def resolve_repository(self, repository_url: str, paper_id: str | None = None) -> CodeRecord | None:
        repository = repository_url.removeprefix("https://github.com/").strip("/")
        try:
            metadata = await self.http.get_json(f"{self.base_url}/repos/{quote(repository, safe='/')}")
            branch = metadata.data.get("default_branch") or "main"
            commit = await self.http.get_json(f"{self.base_url}/repos/{quote(repository, safe='/')}/commits/{quote(branch, safe='')}")
        except ProviderFailure as error:
            if error.status_code == 404:
                return None
            raise
        item = metadata.data
        html_url = item.get("html_url")
        sha = commit.data.get("sha")
        if not html_url or not sha:
            # Same defense in depth as get_work: an incomplete/unexpected response
            # (renamed repo edge cases, transient API quirks) degrades to "unresolvable"
            # instead of raising a raw KeyError that fails the whole ingestion item.
            return None
        digest_input = json.dumps({"repository": html_url, "commit": sha}, sort_keys=True)
        return CodeRecord(
            repository_url=html_url, pinned_commit=sha,
            license=(item.get("license") or {}).get("spdx_id"), stars=item.get("stargazers_count"),
            topics=item.get("topics") or [], paper_id=paper_id, source_url=html_url,
            retrieved_at=datetime.now(UTC).isoformat(), content_hash=hashlib.sha256(digest_input.encode()).hexdigest(),
            verified=bool(sha and (item.get("license") or {}).get("spdx_id")),
        )

    async def search_code_records(self, query: str, language: str, min_stars: int, limit: int) -> tuple[list[CodeRecord], int]:
        search_query = f"{query} language:{language} stars:>={min_stars}"
        try:
            response = await self.http.get_json(
                f"{self.base_url}/search/repositories", params={"q": search_query, "per_page": limit, "sort": "stars"}
            )
        except ProviderFailure:
            raise
        records: list[CodeRecord] = []
        attempts = response.attempts
        for item in response.data.get("items", [])[:limit]:
            html_url = item.get("html_url")
            if not html_url:
                continue
            record = await self.resolve_repository(html_url)
            attempts += 2
            if record:
                records.append(record)
        return records, attempts

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()
