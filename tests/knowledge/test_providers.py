from __future__ import annotations

import json

import httpx
import pytest

from rigor_rs.knowledge.providers.base import ProviderFailure, RetryingHTTPClient
from rigor_rs.knowledge.providers.openalex import OpenAlexProvider


@pytest.mark.asyncio
async def test_provider_does_not_retry_auth_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": "bad key"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderFailure) as failure:
            await RetryingHTTPClient(client, retry_limit=3).get_json("https://example.test")
    assert calls == 1
    assert not failure.value.transient


@pytest.mark.asyncio
async def test_provider_retries_429_with_bound() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "rate"})
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await RetryingHTTPClient(client, retry_limit=3).get_json("https://example.test")
    assert response.data == {"ok": True}
    assert response.attempts == calls == 2


@pytest.mark.asyncio
async def test_openalex_preserves_retraction_and_license() -> None:
    payload = {
        "id": "https://openalex.org/W1",
        "display_name": "Retracted Example",
        "publication_year": 2024,
        "is_retracted": True,
        "ids": {"doi": "https://doi.org/10.1/example"},
        "authorships": [],
        "primary_location": {"source": {"display_name": "Venue"}},
        "best_oa_location": {"license": "cc-by", "landing_page_url": "https://example.test/paper"},
        "abstract_inverted_index": {"safe": [0], "abstract": [1]},
        "referenced_works": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(payload).encode())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAlexProvider(api_key="test", mailto=None, timeout_seconds=1, retry_limit=0, client=client)
        work = await provider.get_work("W1")
    assert work is not None
    assert work.retracted
    assert work.license == "cc-by"
    assert work.abstract == "safe abstract"
    assert work.identifiers.doi == "10.1/example"
