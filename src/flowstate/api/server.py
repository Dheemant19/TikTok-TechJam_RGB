from __future__ import annotations

import asyncio
import json
from contextlib import suppress
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from flowstate.contract.models import ComponentStatus
from flowstate.ledger.workflow import WorkflowLedger


REDACTED = "Hidden to protect data and credentials"
# Specific compound field names: substring match is safe, these are too
# distinctive to collide with an unrelated field.
_SECRET_KEY_SUBSTRINGS = {"azure_foundry_api_key", "github_token"}
# Generic single words: substring matching here previously redacted innocuous
# fields like bedrock_input_tokens/bedrock_output_tokens (an LLM usage count,
# not a credential) purely because "tokens" contains "token". Require a whole
# word match instead.
_SECRET_WORDS = {"password", "secret", "token"}
_PROTECTED_KEYS = {"test_labels", "validation_labels", "raw_rows", "checkpoint_bytes"}


def redact(value: Any, key: str = "") -> Any:
    lowered = key.casefold()
    words = re.findall(r"[a-z0-9]+", lowered)
    is_secret = (
        lowered in _PROTECTED_KEYS
        or any(secret in lowered for secret in _SECRET_KEY_SUBSTRINGS)
        or any(word in _SECRET_WORDS for word in words)
    )
    if is_secret:
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

class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4_000)


class SessionChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4_000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


def _session_chat_context(ledger: WorkflowLedger, session_id: str) -> dict[str, Any]:
    snapshot = redact(ledger.snapshot(session_id).model_dump(mode="json"))
    timeline: list[dict[str, Any]] = []
    for event in ledger.events(session_id):
        payload = redact(event.payload)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        timeline.append({
            "sequence": event.sequence,
            "run_id": event.run_id,
            "component": event.component_id,
            "stage": event.stage,
            "event_type": event.event_type,
            "status": event.status,
            "occurred_at": str(event.occurred_at),
            "summary": event.plain_summary,
            "payload": payload if len(encoded) <= 2_000 else {
                "truncated": True,
                "preview": encoded[:2_000],
            },
            "artifact_ids": event.artifact_ids,
        })
    return {"snapshot": snapshot, "timeline": timeline}


class WorkflowHost:
    def __init__(
        self, ledger: WorkflowLedger,
        workflow_factory: Callable[[str, str], Any],
        package_callback: Callable[[str], dict[str, Any]],
        chat_callback: Callable[[dict[str, Any], str, list[dict[str, str]]], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self.ledger = ledger
        self.workflow_factory = workflow_factory
        self.package_callback = package_callback
        self.chat_callback = chat_callback
        self.tasks: dict[str, asyncio.Task[Any]] = {}

    def start(self, challenge: str, budget: str) -> str:
        session_id = self.ledger.create_session()
        workflow = self.workflow_factory(challenge, budget)
        task = asyncio.create_task(workflow.run(session_id))
        self.tasks[session_id] = task

        def discard(completed: asyncio.Task[Any]) -> None:
            self.tasks.pop(session_id, None)
            if not completed.cancelled():
                # Retrieve the exception so the event loop does not emit
                # "Task exception was never retrieved". workflow.run already
                # records the fatal error and marks the session failed.
                completed.exception()

        task.add_done_callback(discard)
        return session_id

    def package(self, session_id: str) -> dict[str, Any]:
        snapshot = self.ledger.snapshot(session_id)
        if "package" not in snapshot.allowed_actions:
            raise RuntimeError(
                f"package is not allowed while session is {snapshot.status}; "
                "the workflow must finish with a locked validation-best result"
            )
        return self.package_callback(session_id)


def create_app(host: WorkflowHost, ui_dist: Path | None = None) -> FastAPI:
    app = FastAPI(title="FlowState Observer API", version="1.0.0")

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

    @app.delete("/api/v1/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str) -> Response:
        try:
            snapshot_value = host.ledger.snapshot(session_id)
        except KeyError as error:
            raise HTTPException(404, detail="session not found") from error
        task = host.tasks.get(session_id)
        if task is not None and not task.done():
            if not snapshot_value.cancelled:
                raise HTTPException(409, detail="Stop the running session before deleting it")
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        try:
            host.ledger.delete_session(session_id)
        except KeyError as error:
            raise HTTPException(404, detail="session not found") from error
        return Response(status_code=204)

    @app.get("/api/v1/sessions/{session_id}/package/{filename}")
    def download_package_file(session_id: str, filename: str) -> FileResponse:
        if filename not in {"predictions.csv", "manifest.json"}:
            raise HTTPException(404, detail="package file not found")
        with host.ledger.connect() as connection:
            row = connection.execute(
                "SELECT manifest_path FROM finalizations WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(404, detail="session has no final package")
        manifest_path = Path(row["manifest_path"]).resolve()
        package_directory = manifest_path.parent
        requested = (package_directory / filename).resolve()
        if requested.parent != package_directory or not requested.is_file():
            raise HTTPException(404, detail="package file not found")
        media_type = "text/csv" if filename == "predictions.csv" else "application/json"
        return FileResponse(requested, media_type=media_type, filename=filename)

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

    @app.post("/api/v1/sessions/{session_id}/chat")
    async def session_chat(session_id: str, request: SessionChatRequest) -> dict[str, Any]:
        if host.chat_callback is None:
            raise HTTPException(503, detail="session chat is not configured")
        try:
            context = _session_chat_context(host.ledger, session_id)
        except KeyError as error:
            raise HTTPException(404, detail="session not found") from error
        try:
            return await host.chat_callback(
                context,
                request.question,
                [message.model_dump(mode="json") for message in request.history],
            )
        except Exception as error:
            raise HTTPException(502, detail=f"session chat failed: {error}") from error

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
            if action == "cancel":
                task = host.tasks.get(session_id)
                if task is not None and not task.done():
                    task.cancel()
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
            return host.package(session_id)
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
