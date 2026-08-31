from __future__ import annotations

from flowstate.knowledge.models import EvidenceFilters, ProviderResult, ProviderWork
from flowstate.knowledge.providers.base import KnowledgeProvider


class PapersWithCodeProvider(KnowledgeProvider):
    name = "papers_with_code"

    def __init__(self, *, enabled: bool, endpoint: str | None) -> None:
        self.enabled = enabled
        self.endpoint = endpoint

    def _unavailable(self) -> ProviderResult:
        reason = "Papers-with-Code provider is disabled" if not self.enabled else "configured endpoint is unavailable"
        return ProviderResult(error="provider_unavailable", error_message=reason)

    async def search(self, query: str, filters: EvidenceFilters | None, limit: int) -> ProviderResult:
        return self._unavailable()

    async def get_work(self, identifier: str) -> ProviderWork | None:
        return None

    async def get_citations(self, identifier: str, direction: str, limit: int) -> ProviderResult:
        return self._unavailable()
