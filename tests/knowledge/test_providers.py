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


@pytest.mark.asyncio
async def test_github_get_readme_decodes_base64_content() -> None:
    import base64

    from rigor_rs.knowledge.providers.github import GitHubProvider

    readme_text = "# BPR\n\nUsage:\n```python\nmodel = BPR(n_users, n_items)\n```\n"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/readme")
        return httpx.Response(200, json={
            "content": base64.b64encode(readme_text.encode("utf-8")).decode("ascii"),
            "encoding": "base64",
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(token=None, timeout_seconds=1, retry_limit=0, client=client)
    result = await provider.get_readme("https://github.com/example/bpr", ref="deadbeef")
    assert result == readme_text


@pytest.mark.asyncio
async def test_github_get_readme_returns_none_on_404() -> None:
    from rigor_rs.knowledge.providers.github import GitHubProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(token=None, timeout_seconds=1, retry_limit=0, client=client)
    result = await provider.get_readme("https://github.com/example/missing-repo")
    assert result is None


@pytest.mark.asyncio
async def test_github_list_python_files_excludes_tests_and_ranks_by_depth() -> None:
    from rigor_rs.knowledge.providers.github import GitHubProvider

    tree_payload = {
        "tree": [
            {"path": "model.py", "type": "blob"},
            {"path": "src/deep/nested/module.py", "type": "blob"},
            {"path": "tests/test_model.py", "type": "blob"},
            {"path": "examples/demo.py", "type": "blob"},
            {"path": "README.md", "type": "blob"},
            {"path": "src/layers.py", "type": "blob"},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/git/trees/" in request.url.path
        return httpx.Response(200, json=tree_payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(token=None, timeout_seconds=1, retry_limit=0, client=client)
    paths = await provider.list_python_files("https://github.com/example/repo", "deadbeef", limit=3)

    assert "tests/test_model.py" not in paths
    assert "examples/demo.py" not in paths
    assert "README.md" not in paths
    assert paths[0] == "model.py"  # shallowest real implementation file ranks first
    assert len(paths) <= 3


@pytest.mark.asyncio
async def test_github_get_file_content_decodes_base64() -> None:
    import base64

    from rigor_rs.knowledge.providers.github import GitHubProvider

    source = "class BPR(nn.Module):\n    pass\n"

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/contents/" in request.url.path
        return httpx.Response(200, json={
            "content": base64.b64encode(source.encode("utf-8")).decode("ascii"),
            "encoding": "base64",
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(token=None, timeout_seconds=1, retry_limit=0, client=client)
    result = await provider.get_file_content("https://github.com/example/repo", "model.py", "deadbeef")
    assert result == source
