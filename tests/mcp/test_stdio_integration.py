from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.asyncio
async def test_stdio_offline_search_and_tool_surface(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    config_document = yaml.safe_load((root / "configs/knowledge/research.yaml").read_text(encoding="utf-8"))
    # Use a fresh, isolated database rather than the shared dev state/knowledge.sqlite3:
    # manual/interactive testing against the shared file (e.g. --resolve-code runs)
    # would otherwise silently change this test's expected unresolved-code assertions.
    config_document["storage"]["database"] = str(tmp_path / "test-knowledge.sqlite3")
    config_document["providers"]["huggingface_papers"]["enabled"] = False
    config_document["providers"]["github"]["enabled"] = False
    offline_config = tmp_path / "offline-knowledge.yaml"
    offline_config.write_text(yaml.safe_dump(config_document, sort_keys=False), encoding="utf-8")
    environment["HF_HUB_OFFLINE"] = "1"
    environment["FLOWSTATE_MCP_TRANSPORT"] = "stdio"
    environment["FLOWSTATE_KNOWLEDGE_CONFIG"] = str(offline_config)
    environment["FLOWSTATE_SESSION_ID"] = f"mcp-smoke-{uuid.uuid4().hex}"
    environment["FLOWSTATE_EXPERIMENT_ID"] = "offline-tools"
    subprocess.run(
        [sys.executable, "-m", "flowstate.cli", "knowledge", "ingest-curated",
         "--config", str(offline_config), "--no-enrich", "--no-resolve-code"],
        cwd=str(root), env=environment, check=True, capture_output=True,
    )
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "flowstate.mcp.server"],
        cwd=str(root),
        env=environment,
    )
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "search_evidence", "get_paper", "get_fulltext", "search_code",
                "get_code_for_paper", "discover_paper_with_code", "expand_citations", "get_research_card",
            }
            response = await session.call_tool(
                "search_evidence",
                {"query": "GAUC", "semantic": False, "max_results": 2},
            )
            assert not response.isError
            structured = response.structuredContent
            assert structured is not None
            assert structured["results"]
            assert structured["meta"]["selected_record_ids"]
            semantic = await session.call_tool(
                "search_evidence",
                {
                    "query": "loss aligned with within-user ranking",
                    "semantic": True,
                    "filters": {"priority_area": "ranking_loss_alignment"},
                    "max_results": 2,
                },
            )
            assert not semantic.isError
            semantic_content = semantic.structuredContent
            assert semantic_content is not None
            assert semantic_content["results"]
            assert all(
                "ranking_loss_alignment" in item["paper"]["priority_areas"]
                for item in semantic_content["results"]
            )
            cached = await session.call_tool(
                "search_evidence",
                {"query": "  gauc  ", "semantic": False, "max_results": 2},
            )
            assert cached.structuredContent["meta"]["cache_status"] == "hit"
            paper = await session.call_tool("get_paper", {"paper_id": "arxiv:1205.2618"})
            fulltext = await session.call_tool("get_fulltext", {"paper_id": "arxiv:1205.2618"})
            code_search = await session.call_tool("search_code", {"query": "bpr", "max_results": 3})
            paper_code = await session.call_tool("get_code_for_paper", {"paper_id": "arxiv:1205.2618"})
            citations = await session.call_tool(
                "expand_citations",
                {"work_id": "arxiv:1205.2618", "direction": "cites", "max_results": 2},
            )
            research_card = await session.call_tool(
                "get_research_card",
                {"hypothesis": "pairwise ranking loss improves within-user ranking", "max_evidence": 4},
            )
            for tool_result in (paper, fulltext, code_search, paper_code, citations, research_card):
                assert not tool_result.isError
                assert tool_result.structuredContent is not None
            assert paper.structuredContent["paper"]["paper_id"] == "arxiv:1205.2618"
            assert fulltext.structuredContent["available"] is False
            assert code_search.structuredContent["results"] == []
            assert paper_code.structuredContent["results"] == []
            assert research_card.structuredContent["source_ids"]
