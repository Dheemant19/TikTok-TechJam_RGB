from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from rigor_rs.knowledge.models import EvidenceFilters, PaperIdentifiers, ProviderResult, ProviderWork
from rigor_rs.knowledge.providers.base import KnowledgeProvider, ProviderFailure, RetryingHTTPClient


class OpenAlexProvider(KnowledgeProvider):
    name = "openalex"
    base_url = "https://api.openalex.org"

    def __init__(
        self, *, api_key: str | None, mailto: str | None, timeout_seconds: float,
        retry_limit: int, client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.mailto = mailto
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=timeout_seconds, headers={"User-Agent": "RIGOR-RS/0.1"}, follow_redirects=True)
        self.http = RetryingHTTPClient(self.client, retry_limit)

    def _params(self, values: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(values or {})
        if self.api_key:
            params["api_key"] = self.api_key
        if self.mailto:
            params["mailto"] = self.mailto
        return params

    @staticmethod
    def _abstract(inverted: dict[str, list[int]] | None) -> str | None:
        if not inverted:
            return None
        positions = [(position, word) for word, values in inverted.items() for position in values]
        return " ".join(word for _, word in sorted(positions))

    @staticmethod
    def _identifier(value: str | None) -> str | None:
        return value.rsplit("/", 1)[-1] if value else None

    def _normalize(self, work: dict[str, Any], response_hash: str) -> ProviderWork:
        ids = work.get("ids") or {}
        openalex_id = self._identifier(work.get("id"))
        doi = ids.get("doi") or work.get("doi")
        arxiv = ids.get("arxiv")
        best_oa = work.get("best_oa_location") or {}
        primary = work.get("primary_location") or {}
        source = primary.get("source") or {}
        license_value = best_oa.get("license") or primary.get("license")
        authors = [
            item.get("author", {}).get("display_name")
            for item in work.get("authorships", [])
            if item.get("author", {}).get("display_name")
        ]
        return ProviderWork(
            paper_id=f"openalex:{openalex_id.casefold()}" if openalex_id else f"openalex:unknown-{response_hash[:12]}",
            title=work.get("display_name") or work.get("title") or "Untitled work",
            authors=authors,
            year=work.get("publication_year"),
            venue=source.get("display_name"),
            abstract=self._abstract(work.get("abstract_inverted_index")),
            identifiers=PaperIdentifiers(doi=doi, arxiv_id=arxiv, openalex_id=openalex_id),
            paper_url=best_oa.get("landing_page_url") or work.get("doi") or work.get("id"),
            license=license_value,
            retracted=bool(work.get("is_retracted")),
            cited_by_ids=[],
            referenced_ids=[self._identifier(value) for value in work.get("referenced_works", []) if value],
            source=self.name,
            source_url=work.get("id"),
            raw_response_hash=response_hash,
        )

    async def search(self, query: str, filters: EvidenceFilters | None, limit: int) -> ProviderResult:
        params: dict[str, Any] = {"search": query, "per-page": limit, "select": "id,doi,display_name,publication_year,authorships,primary_location,best_oa_location,abstract_inverted_index,ids,is_retracted,referenced_works"}
        filter_parts: list[str] = []
        if filters and filters.year_from:
            filter_parts.append(f"from_publication_date:{filters.year_from}-01-01")
        if filters and filters.year_to:
            filter_parts.append(f"to_publication_date:{filters.year_to}-12-31")
        if filters and filters.require_license:
            filter_parts.append("has_fulltext:true")
        if filter_parts:
            params["filter"] = ",".join(filter_parts)
        try:
            response = await self.http.get_json(f"{self.base_url}/works", params=self._params(params))
        except ProviderFailure as error:
            return ProviderResult(
                attempts=error.attempts, error="transient_failure" if error.transient else "invalid_request",
                error_message=str(error),
            )
        records = [self._normalize(work, response.response_hash) for work in response.data.get("results", [])]
        return ProviderResult(records=records, attempts=response.attempts)

    async def get_work(self, identifier: str) -> ProviderWork | None:
        try:
            response = await self.http.get_json(
                f"{self.base_url}/works/{quote(identifier, safe='')}", params=self._params()
            )
        except ProviderFailure as error:
            if error.status_code == 404:
                return None
            raise
        return self._normalize(response.data, response.response_hash)

    async def get_citations(self, identifier: str, direction: str, limit: int) -> ProviderResult:
        if direction == "cites":
            work = await self.get_work(identifier)
            if work is None:
                return ProviderResult(error="not_found", error_message="OpenAlex work not found")
            records: list[ProviderWork] = []
            for cited_id in work.referenced_ids[:limit]:
                record = await self.get_work(cited_id)
                if record:
                    records.append(record)
            return ProviderResult(records=records, attempts=max(1, len(records) + 1))
        params = {"filter": f"cites:{identifier}", "per-page": limit}
        try:
            response = await self.http.get_json(f"{self.base_url}/works", params=self._params(params))
        except ProviderFailure as error:
            return ProviderResult(
                attempts=error.attempts, error="transient_failure" if error.transient else "invalid_request",
                error_message=str(error),
            )
        return ProviderResult(
            records=[self._normalize(work, response.response_hash) for work in response.data.get("results", [])],
            attempts=response.attempts,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()
