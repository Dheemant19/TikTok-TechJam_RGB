from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from flowstate.knowledge.models import ToolLifecycleEvent
from flowstate.ledger.mcp import MCPReceiptMirror
from flowstate.mcp.server import get_application


@pytest.mark.asyncio
async def test_exact_agent_tool_surface() -> None:
    tools = await get_application().mcp.list_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "search_evidence", "get_paper", "get_fulltext", "search_code",
        "get_code_for_paper", "discover_paper_with_code", "expand_citations", "get_research_card",
    }
    assert "submit_curated_paper" not in names


def test_ledger_mirror_is_append_only(tmp_path: Path) -> None:
    database = tmp_path / "flowstate.sqlite3"
    mirror = MCPReceiptMirror(database)
    event = ToolLifecycleEvent(
        receipt_id="receipt-1", request_id="request-1", tool_name="search_evidence",
        query_hash="a" * 64, lifecycle="completed", selected_evidence_ids=["paper-1"],
        provider_requests=2, documents_returned=3, response_characters=400,
    )
    mirror.append(event)
    with pytest.raises(sqlite3.IntegrityError):
        mirror.append(event)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """SELECT request_id,selected_evidence_ids_json,provider_requests,
               documents_returned,response_characters FROM mcp_receipts"""
        ).fetchone()
    assert row == ("request-1", '["paper-1"]', 2, 3, 400)
