from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from rigor_rs.contract.models import ArtifactRef, ComponentStatus, FrontierState, RunEvent, SessionSnapshot


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str).encode()).hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"


SCHEMA = """
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS workflow_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
 session_id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
 latest_sequence INTEGER NOT NULL DEFAULT 0, finalized INTEGER NOT NULL DEFAULT 0,
 cancelled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS run_events(
 event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id), run_id TEXT NOT NULL,
 sequence INTEGER NOT NULL, component_id TEXT NOT NULL, execution_id TEXT NOT NULL, stage TEXT NOT NULL,
 event_type TEXT NOT NULL, status TEXT NOT NULL, occurred_at TEXT NOT NULL, plain_summary TEXT NOT NULL,
 payload_json TEXT NOT NULL, artifact_ids_json TEXT NOT NULL, previous_event_hash TEXT, event_hash TEXT NOT NULL UNIQUE,
 UNIQUE(session_id,sequence));
CREATE TABLE IF NOT EXISTS artifacts(
 artifact_id TEXT PRIMARY KEY, path TEXT NOT NULL, content_hash TEXT NOT NULL UNIQUE, media_type TEXT NOT NULL,
 taint TEXT, parent_ids_json TEXT NOT NULL, row_count INTEGER, schema_fingerprint TEXT,
 source_hashes_json TEXT NOT NULL, code_hash TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS experiment_contracts(
 experiment_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, contract_json TEXT NOT NULL,
 content_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metric_receipts(
 receipt_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, run_id TEXT NOT NULL,
 receipt_json TEXT NOT NULL, receipt_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS frontier_entries(
 entry_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, run_id TEXT NOT NULL,
 role TEXT NOT NULL, active INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recovery_attempts(
 recovery_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, run_id TEXT NOT NULL,
 receipt_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS resource_samples(
 sample_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, run_id TEXT NOT NULL,
 sample_json TEXT NOT NULL, occurred_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS manual_interventions(
 intervention_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, action TEXT NOT NULL,
 reason TEXT NOT NULL, occurred_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS control_requests(
 request_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, action TEXT NOT NULL,
 expected_sequence INTEGER NOT NULL, accepted INTEGER NOT NULL, reason TEXT, occurred_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS finalizations(
 session_id TEXT PRIMARY KEY, manifest_hash TEXT NOT NULL, manifest_path TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[RunEvent]]] = {}
        self._lock = threading.Lock()

    def subscribe(self, session_id: str) -> asyncio.Queue[RunEvent]:
        queue: asyncio.Queue[RunEvent] = asyncio.Queue()
        with self._lock:
            self._subscribers.setdefault(session_id, []).append(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[RunEvent]) -> None:
        with self._lock:
            values = self._subscribers.get(session_id, [])
            if queue in values:
                values.remove(queue)

    def publish(self, event: RunEvent) -> None:
        with self._lock:
            queues = list(self._subscribers.get(event.session_id, []))
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass


class WorkflowLedger:
    def __init__(self, database: Path, bus: EventBus | None = None) -> None:
        self.database = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.bus = bus or EventBus()
        self._lock = threading.RLock()
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute("INSERT OR IGNORE INTO workflow_migrations VALUES(1,?)", (datetime.now(UTC).isoformat(),))

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def create_session(self) -> str:
        session_id = new_id("session")
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO sessions(session_id,status,created_at) VALUES(?,?,?)",
                (session_id, ComponentStatus.READY, datetime.now(UTC).isoformat()),
            )
        return session_id
    def set_session_status(self, session_id: str, status: ComponentStatus) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE sessions SET status=? WHERE session_id=?",
                (status.value, session_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown session {session_id}")


    def append_event(
        self, *, session_id: str, run_id: str, component_id: str, execution_id: str,
        stage: str, event_type: str, status: ComponentStatus, plain_summary: str,
        payload: dict[str, Any] | None = None, artifact_ids: list[str] | None = None,
    ) -> RunEvent:
        occurred_at = datetime.now(UTC).isoformat()
        with self.transaction() as connection:
            session = connection.execute("SELECT latest_sequence FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if not session:
                raise KeyError(f"unknown session {session_id}")
            sequence = int(session["latest_sequence"]) + 1
            previous = connection.execute(
                "SELECT event_hash FROM run_events WHERE session_id=? ORDER BY sequence DESC LIMIT 1", (session_id,)
            ).fetchone()
            previous_hash = previous["event_hash"] if previous else None
            unsigned = {
                "event_id": new_id("event"), "session_id": session_id, "run_id": run_id,
                "sequence": sequence, "component_id": component_id, "execution_id": execution_id,
                "stage": stage, "event_type": event_type, "status": status.value,
                "occurred_at": occurred_at, "plain_summary": plain_summary, "payload": payload or {},
                "artifact_ids": artifact_ids or [], "previous_event_hash": previous_hash,
            }
            event = RunEvent(**unsigned, event_hash=canonical_hash(unsigned))
            connection.execute(
                """INSERT INTO run_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event.event_id, event.session_id, event.run_id, event.sequence, event.component_id,
                 event.execution_id, event.stage, event.event_type, event.status, event.occurred_at,
                 event.plain_summary, json.dumps(event.payload, sort_keys=True), json.dumps(event.artifact_ids),
                 event.previous_event_hash, event.event_hash),
            )
            connection.execute(
                "UPDATE sessions SET latest_sequence=? WHERE session_id=?",
                (sequence, session_id),
            )
        self.bus.publish(event)
        return event

    def events(self, session_id: str, after_sequence: int = 0) -> list[RunEvent]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM run_events WHERE session_id=? AND sequence>? ORDER BY sequence", (session_id, after_sequence)
            ).fetchall()
        return [RunEvent(
            event_id=row["event_id"], session_id=row["session_id"], run_id=row["run_id"], sequence=row["sequence"],
            component_id=row["component_id"], execution_id=row["execution_id"], stage=row["stage"],
            event_type=row["event_type"], status=row["status"], occurred_at=row["occurred_at"],
            plain_summary=row["plain_summary"], payload=json.loads(row["payload_json"]),
            artifact_ids=json.loads(row["artifact_ids_json"]), previous_event_hash=row["previous_event_hash"],
            event_hash=row["event_hash"],
        ) for row in rows]

    def verify_chain(self, session_id: str) -> bool:
        previous: str | None = None
        for event in self.events(session_id):
            unsigned = event.model_dump(exclude={"event_hash"}, mode="json")
            if event.previous_event_hash != previous or canonical_hash(unsigned) != event.event_hash:
                return False
            previous = event.event_hash
        return True

    def snapshot(self, session_id: str) -> SessionSnapshot:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            raise KeyError(session_id)
        snapshot = SessionSnapshot(
            session_id=session_id, latest_sequence=row["latest_sequence"], status=row["status"],
            finalized=bool(row["finalized"]), cancelled=bool(row["cancelled"]),
            manual_interventions=self.manual_intervention_count(session_id),
        )
        for event in self.events(session_id):
            snapshot.component_states[event.component_id] = event.status
            snapshot.current_run_id = event.run_id
            if event.event_type == "metric":
                snapshot.metrics.update(event.payload.get("metrics", {}))
            if event.event_type == "frontier":
                snapshot.frontier = FrontierState.model_validate(event.payload["frontier"])
        if snapshot.finalized or snapshot.cancelled:
            snapshot.allowed_actions = []
        elif snapshot.status == ComponentStatus.PAUSED:
            snapshot.allowed_actions = ["resume", "cancel"]
        elif snapshot.status == ComponentStatus.RUNNING:
            snapshot.allowed_actions = ["pause", "cancel"]
        elif snapshot.status == ComponentStatus.SUCCEEDED:
            snapshot.allowed_actions = ["package"] if snapshot.frontier.locked and snapshot.frontier.validation_best else []
        elif snapshot.status == ComponentStatus.FAILED:
            snapshot.allowed_actions = []
        else:
            snapshot.allowed_actions = ["cancel"]
        return snapshot

    def register_artifact(self, artifact: ArtifactRef) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (artifact.artifact_id, str(artifact.path), artifact.content_hash, artifact.media_type,
                 artifact.taint.value if artifact.taint else None, json.dumps(artifact.parent_ids), artifact.row_count,
                 artifact.schema_fingerprint, json.dumps(artifact.source_hashes, sort_keys=True), artifact.code_hash,
                 artifact.created_at),
            )

    def get_artifact(self, artifact_id: str) -> ArtifactRef | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
        if not row:
            return None
        return ArtifactRef(
            artifact_id=row["artifact_id"], path=Path(row["path"]), content_hash=row["content_hash"],
            media_type=row["media_type"], taint=row["taint"], parent_ids=json.loads(row["parent_ids_json"]),
            row_count=row["row_count"], schema_fingerprint=row["schema_fingerprint"],
            source_hashes=json.loads(row["source_hashes_json"]), code_hash=row["code_hash"], created_at=row["created_at"],
        )

    def store_contract(self, session_id: str, experiment_id: str, document: dict[str, Any]) -> str:
        content_hash = canonical_hash(document)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO experiment_contracts VALUES(?,?,?,?,?)",
                (experiment_id, session_id, json.dumps(document, sort_keys=True), content_hash, datetime.now(UTC).isoformat()),
            )
        return content_hash

    def list_contracts(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT contract_json FROM experiment_contracts WHERE session_id=? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        return [json.loads(row["contract_json"]) for row in rows]
    # Explicit intervention policy (Plan_Workflow §12.4): pausing, resuming or
    # cancelling an autonomous run is a human decision and counts. Starting a
    # session and confirming the one-way final package are required operator
    # actions in the organizer's own procedure, so they are recorded as control
    # events but are not counted as interventions.
    INTERVENTION_ACTIONS = {"pause", "resume", "cancel"}

    def record_manual_intervention(self, session_id: str, action: str, reason: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO manual_interventions VALUES(?,?,?,?,?)",
                (new_id("intervention"), session_id, action, reason, datetime.now(UTC).isoformat()),
            )

    def manual_intervention_count(self, session_id: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM manual_interventions WHERE session_id=?",
                (session_id,),
            ).fetchone()
        return int(row["total"]) if row else 0

    def store_metric_receipt(self, session_id: str, run_id: str, document: dict[str, Any]) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO metric_receipts VALUES(?,?,?,?,?,?)",
                (
                    document["receipt_id"], session_id, run_id,
                    json.dumps(document, sort_keys=True), document["receipt_hash"],
                    datetime.now(UTC).isoformat(),
                ),
            )

    def store_recovery_receipt(self, session_id: str, run_id: str, document: dict[str, Any]) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO recovery_attempts VALUES(?,?,?,?,?)",
                (
                    document["recovery_id"], session_id, run_id,
                    json.dumps(document, sort_keys=True), datetime.now(UTC).isoformat(),
                ),
            )

    def store_resource_sample(self, session_id: str, run_id: str, document: dict[str, Any]) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO resource_samples(session_id,run_id,sample_json,occurred_at) VALUES(?,?,?,?)",
                (session_id, run_id, json.dumps(document, sort_keys=True), datetime.now(UTC).isoformat()),
            )

    def store_frontier(self, session_id: str, frontier: FrontierState) -> None:
        roles = {
            "validation_best": frontier.validation_best,
            "stable_fallback": frontier.stable_fallback,
            "accepted_parent": frontier.accepted_parent,
        }
        with self.transaction() as connection:
            connection.execute("UPDATE frontier_entries SET active=0 WHERE session_id=? AND active=1", (session_id,))
            now = datetime.now(UTC).isoformat()
            for role, run_id in roles.items():
                if run_id:
                    connection.execute(
                        "INSERT INTO frontier_entries(session_id,run_id,role,active,created_at) VALUES(?,?,?,?,?)",
                        (session_id, run_id, role, 1, now),
                    )

    def control(self, session_id: str, action: str, expected_sequence: int) -> tuple[bool, str]:
        snapshot = self.snapshot(session_id)
        if expected_sequence != snapshot.latest_sequence:
            return False, "stale sequence; reload the authoritative snapshot"
        if action not in snapshot.allowed_actions:
            return False, f"{action} is not allowed while session is {snapshot.status}"
        next_status = {
            "pause": ComponentStatus.PAUSED,
            "resume": ComponentStatus.RUNNING,
            "cancel": ComponentStatus.FAILED,
        }.get(action)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO control_requests VALUES(?,?,?,?,?,?,?)",
                (new_id("control"), session_id, action, expected_sequence, 1, None, datetime.now(UTC).isoformat()),
            )
            if next_status is not None:
                connection.execute(
                    "UPDATE sessions SET cancelled=?,status=? WHERE session_id=?",
                    (1 if action == "cancel" else 0, next_status.value, session_id),
                )
        if action in self.INTERVENTION_ACTIONS:
            self.record_manual_intervention(
                session_id, action, f"operator requested {action} at sequence {expected_sequence}"
            )
        return True, "accepted"
