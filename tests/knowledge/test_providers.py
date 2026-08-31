from __future__ import annotations

import json

import httpx
import pytest

from flowstate.knowledge.providers.base import ProviderFailure, RetryingHTTPClient
from flowstate.knowledge.providers.huggingface_papers import HuggingFacePapersProvider


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
async def test_huggingface_search_hard_checks_github_repo() -> None:
    entries = [
        {"paper": {"id": "2401.00001", "title": "No Code Here", "authors": [], "publishedAt": "2024-01-01T00:00:00.000Z", "summary": "s"}},
        {"paper": {
            "id": "2401.00002", "title": "Has Code", "authors": [{"name": "A"}],
            "publishedAt": "2024-01-02T00:00:00.000Z", "summary": "s",
            "githubRepo": "https://github.com/example/has-code",
        }},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(entries).encode())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = HuggingFacePapersProvider(timeout_seconds=1, retry_limit=0, client=client)
        result = await provider.search("recommendation", None, 1, session_id="s1")

    assert len(result.records) == 1
    record = result.records[0]
    assert record.paper_id == "huggingface:2401.00002"
    assert str(record.github_repositories[0].url) == "https://github.com/example/has-code"


@pytest.mark.asyncio
async def test_huggingface_search_returns_requested_fresh_code_linked_papers() -> None:
    requested_limits: list[int] = []
    entries = [
        {"paper": {
            "id": f"2401.0000{index}", "title": f"Paper {index}", "authors": [],
            "publishedAt": "2024-01-02T00:00:00.000Z", "summary": "ranking",
            "githubRepo": f"https://github.com/example/paper-{index}",
        }}
        for index in range(1, 5)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        limit = int(request.url.params["limit"])
        requested_limits.append(limit)
        return httpx.Response(200, content=json.dumps(entries[:limit]).encode())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = HuggingFacePapersProvider(timeout_seconds=1, retry_limit=0, client=client)
        result = await provider.search("recommendation", None, 3, session_id="s1")

    assert requested_limits == [3]
    assert [record.paper_id for record in result.records] == [
        "huggingface:2401.00001",
        "huggingface:2401.00002",
        "huggingface:2401.00003",
    ]


@pytest.mark.asyncio
async def test_huggingface_search_never_repeats_a_paper_within_a_session() -> None:
    seen_paper = {
        "paper": {
            "id": "2401.00002", "title": "Has Code", "authors": [],
            "publishedAt": "2024-01-02T00:00:00.000Z", "summary": "s",
            "githubRepo": "https://github.com/example/has-code",
        },
    }
    fresh_paper = {
        "paper": {
            "id": "2401.00003", "title": "Also Has Code", "authors": [],
            "publishedAt": "2024-01-03T00:00:00.000Z", "summary": "s",
            "githubRepo": "https://github.com/example/also-has-code",
        },
    }
    requested_limits: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        limit = int(request.url.params["limit"])
        requested_limits.append(limit)
        # The API's own top-ranked result never changes; only a wider page
        # size reveals a second, still-relevant candidate.
        entries = [seen_paper] if limit == 1 else [seen_paper, fresh_paper]
        return httpx.Response(200, content=json.dumps(entries).encode())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = HuggingFacePapersProvider(timeout_seconds=1, retry_limit=0, client=client)
        first = await provider.search("recommendation", None, 1, session_id="s1")
        second = await provider.search("recommendation", None, 1, session_id="s1")

    assert first.records[0].paper_id == "huggingface:2401.00002"
    assert second.records[0].paper_id == "huggingface:2401.00003"
    # First call found a fresh candidate on the very first (limit=1) page;
    # the second call had to escalate exactly once (limit=1 then limit=5)
    # because its only candidate on the first page was already seen.
    assert requested_limits == [1, 1, 5]


@pytest.mark.asyncio
async def test_huggingface_get_work_returns_none_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"{}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = HuggingFacePapersProvider(timeout_seconds=1, retry_limit=0, client=client)
        work = await provider.get_work("9999.99999")

    assert work is None



@pytest.mark.asyncio
async def test_github_get_readme_decodes_base64_content() -> None:
    import base64

    from flowstate.knowledge.providers.github import GitHubProvider

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
    from flowstate.knowledge.providers.github import GitHubProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(token=None, timeout_seconds=1, retry_limit=0, client=client)
    result = await provider.get_readme("https://github.com/example/missing-repo")
    assert result is None


@pytest.mark.asyncio
async def test_github_list_python_files_excludes_tests_and_ranks_by_depth() -> None:
    from flowstate.knowledge.providers.github import GitHubProvider

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

    from flowstate.knowledge.providers.github import GitHubProvider

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
