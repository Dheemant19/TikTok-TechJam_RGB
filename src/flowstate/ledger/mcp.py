from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from flowstate.knowledge.models import ToolLifecycleEvent


class MCPReceiptMirror:
    """Append-only, metadata-only mirror consumed by the workflow observer."""

    def __init__(self, database: Path) -> None:
        self.database = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS mcp_receipts(
                   receipt_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, tool_name TEXT NOT NULL,
                   query_hash TEXT NOT NULL, lifecycle TEXT NOT NULL, source_mode TEXT,
                   selected_evidence_ids_json TEXT NOT NULL, duration_ms INTEGER,
                   provider_requests INTEGER NOT NULL, warnings_json TEXT NOT NULL,
                   error_code TEXT, occurred_at TEXT NOT NULL)"""
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(mcp_receipts)")}
            if "documents_returned" not in columns:
                connection.execute("ALTER TABLE mcp_receipts ADD COLUMN documents_returned INTEGER NOT NULL DEFAULT 0")
            if "response_characters" not in columns:
                connection.execute("ALTER TABLE mcp_receipts ADD COLUMN response_characters INTEGER NOT NULL DEFAULT 0")

    def append(self, event: ToolLifecycleEvent) -> None:
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                """INSERT INTO mcp_receipts(receipt_id,request_id,tool_name,query_hash,lifecycle,
                   source_mode,selected_evidence_ids_json,duration_ms,provider_requests,documents_returned,
                   response_characters,warnings_json,error_code,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event.receipt_id, event.request_id, event.tool_name, event.query_hash, event.lifecycle,
                 event.source_mode, json.dumps(event.selected_evidence_ids), event.duration_ms,
                 event.provider_requests, event.documents_returned, event.response_characters,
                 json.dumps(event.warnings), event.error_code, event.occurred_at),
            )
