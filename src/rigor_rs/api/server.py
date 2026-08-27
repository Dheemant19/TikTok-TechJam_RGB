from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from rigor_rs.contract.models import ComponentStatus
from rigor_rs.ledger.workflow import WorkflowLedger


REDACTED = "Hidden to protect data and credentials"
_SECRET_KEYS = {"aws_bearer_token_bedrock", "github_token", "openalex_api_key", "password", "secret", "token"}
_PROTECTED_KEYS = {"test_labels", "validation_labels", "raw_rows", "checkpoint_bytes"}


def redact(value: Any, key: str = "") -> Any:
    lowered = key.casefold()
    if lowered in _PROTECTED_KEYS or any(secret in lowered for secret in _SECRET_KEYS):
        return REDACTED
    if isinstance(value, dict):
        return {item_key: redact(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_config_path: str
    budget_config_path: str


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_sequence: int


class PackageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: str


class WorkflowHost:
    def __init__(
        self, ledger: WorkflowLedger,
        workflow_factory: Callable[[str, str], Any],
        package_callback: Callable[[str], dict[str, Any]],
    ) -> None:
        self.ledger = ledger
        self.workflow_factory = workflow_factory
        self.package_callback = package_callback
        self.tasks: dict[str, asyncio.Task[Any]] = {}

    def start(self, challenge: str, budget: str) -> str:
        session_id = self.ledger.create_session()
        workflow = self.workflow_factory(challenge, budget)
        self.tasks[session_id] = asyncio.create_task(workflow.run(session_id))
        return session_id


def create_app(host: WorkflowHost, ui_dist: Path | None = None) -> FastAPI:
    app = FastAPI(title="RIGOR-RS Observer API", version="1.0.0")

    @app.get("/api/v1/sessions")
    def sessions() -> list[dict[str, Any]]:
        with host.ledger.connect() as connection:
            rows = connection.execute("SELECT session_id,status,created_at,latest_sequence,finalized,cancelled FROM sessions ORDER BY created_at DESC LIMIT 50").fetchall()
        return [dict(row) for row in rows]

    @app.post("/api/v1/sessions", status_code=201)
    async def start(request: StartRequest) -> dict[str, Any]:
        try:
            session_id = host.start(request.challenge_config_path, request.budget_config_path)
        except Exception as error:
            raise HTTPException(422, detail=str(error)) from error
        return {"session_id": session_id, "snapshot_url": f"/api/v1/sessions/{session_id}/snapshot"}

    @app.get("/api/v1/sessions/{session_id}/snapshot")
    def snapshot(session_id: str) -> dict[str, Any]:
        try:
            return redact(host.ledger.snapshot(session_id).model_dump(mode="json"))
        except KeyError as error:
            raise HTTPException(404, detail="session not found") from error

    @app.get("/api/v1/sessions/{session_id}/events")
    async def events(
        session_id: str, after_sequence: int = Query(0, ge=0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        try:
            host.ledger.snapshot(session_id)
        except KeyError as error:
            raise HTTPException(404, detail="session not found") from error
        cursor = max(after_sequence, int(last_event_id or 0))
        async def stream():
            nonlocal cursor
            for event in host.ledger.events(session_id, cursor):
                cursor = event.sequence
                yield f"id: {event.sequence}\nevent: run_event\ndata: {json.dumps(redact(event.model_dump(mode='json')))}\n\n"
            queue = host.ledger.bus.subscribe(session_id)
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                        if event.sequence <= cursor:
                            continue
                        cursor = event.sequence
                        yield f"id: {event.sequence}\nevent: run_event\ndata: {json.dumps(redact(event.model_dump(mode='json')))}\n\n"
                    except asyncio.TimeoutError:
                        yield ": heartbeat\n\n"
            finally:
                host.ledger.bus.unsubscribe(session_id, queue)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/v1/sessions/{session_id}/components/{component_id}/executions/{execution_id}")
    def component_execution(session_id: str, component_id: str, execution_id: str) -> dict[str, Any]:
        values = [event for event in host.ledger.events(session_id) if event.component_id == component_id and event.execution_id == execution_id]
        if not values:
            raise HTTPException(404, detail="execution not found")
        return redact({
            "component_id": component_id, "execution_id": execution_id,
            "attempts": [event.model_dump(mode="json") for event in values],
        })

    @app.get("/api/v1/artifacts/{artifact_id}")
    def artifact(artifact_id: str):
        value = host.ledger.get_artifact(artifact_id)
        if not value:
            raise HTTPException(404, detail="artifact not found")
        metadata = value.model_dump(mode="json")
        path = value.path
        safe_text = value.media_type in {"application/json", "text/plain", "text/x-diff"}
        if safe_text and path.is_file() and path.stat().st_size <= 2_000_000 and value.taint not in {
            "VALIDATION_LABELS", "TEST_LABELS_LOCKED",
        }:
            text = path.read_text(encoding="utf-8", errors="replace")
            if value.media_type == "application/json":
                try:
                    metadata["content"] = redact(json.loads(text))
                except json.JSONDecodeError:
                    metadata["content"] = REDACTED
            else:
                metadata["content"] = redact(text)
        else:
            metadata["content"] = REDACTED
        return metadata

    def control(session_id: str, action: str, request: ControlRequest) -> dict[str, Any]:
        try:
            accepted, reason = host.ledger.control(session_id, action, request.expected_sequence)
        except KeyError as error:
            raise HTTPException(404, detail="session not found") from error
        if not accepted:
            raise HTTPException(409, detail=reason)
        if action in {"pause", "resume", "cancel"}:
            snapshot_value = host.ledger.snapshot(session_id)
            host.ledger.append_event(
                session_id=session_id, run_id=snapshot_value.current_run_id or "workflow", component_id="watchdog",
                execution_id=f"control-{action}", stage="control", event_type=f"control_{action}",
                status=ComponentStatus.PAUSED if action == "pause" else (ComponentStatus.FAILED if action == "cancel" else ComponentStatus.RUNNING),
                plain_summary=f"Session {action} requested", payload={"control": action},
            )
        return {"accepted": True, "action": action}

    @app.post("/api/v1/sessions/{session_id}/pause")
    def pause(session_id: str, request: ControlRequest): return control(session_id, "pause", request)

    @app.post("/api/v1/sessions/{session_id}/resume")
    def resume(session_id: str, request: ControlRequest): return control(session_id, "resume", request)

    @app.post("/api/v1/sessions/{session_id}/cancel")
    def cancel(session_id: str, request: ControlRequest): return control(session_id, "cancel", request)

    @app.post("/api/v1/sessions/{session_id}/package")
    def package(session_id: str, request: PackageRequest):
        if request.confirmation != session_id:
            raise HTTPException(422, detail="confirmation must exactly match session_id")
        try:
            return host.package_callback(session_id)
        except (ValueError, RuntimeError) as error:
            raise HTTPException(409, detail=str(error)) from error

    @app.get("/api/v1/sessions/{session_id}/replay")
    def replay(session_id: str) -> dict[str, Any]:
        try:
            events_value = host.ledger.events(session_id)
            final = host.ledger.snapshot(session_id)
        except KeyError as error:
            raise HTTPException(404, detail="session not found") from error
        return redact({"mode": "replay", "events": [event.model_dump(mode="json") for event in events_value], "final_snapshot": final.model_dump(mode="json")})

    if ui_dist and ui_dist.is_dir():
        app.mount("/assets", StaticFiles(directory=ui_dist / "assets"), name="assets")
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = ui_dist / path
            return FileResponse(candidate if candidate.is_file() else ui_dist / "index.html")

    return app
