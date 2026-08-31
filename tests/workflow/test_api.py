from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from flowstate.api.server import REDACTED, WorkflowHost, create_app
from flowstate.contract.models import ArtifactRef, ComponentStatus
from flowstate.ledger.workflow import WorkflowLedger


def test_snapshot_replay_controls_and_artifact_redaction(tmp_path: Path) -> None:
    ledger = WorkflowLedger(tmp_path / "flowstate.sqlite3")
    session = ledger.create_session()
    ledger.set_session_status(session, ComponentStatus.RUNNING)
    ledger.append_event(
        session_id=session, run_id="run", component_id="trainer", execution_id="exec",
        stage="training", event_type="started", status=ComponentStatus.RUNNING,
        plain_summary="Training", payload={"AWS_BEARER_TOKEN_BEDROCK": "must-not-leak"},
    )
    artifact_path = tmp_path / "safe.json"
    artifact_path.write_text(json.dumps({"metric": 0.6, "github_token": "secret"}), encoding="utf-8")
    artifact = ArtifactRef(
        artifact_id="artifact-1", path=artifact_path, content_hash="a" * 64,
        media_type="application/json",
    )
    ledger.register_artifact(artifact)
    host = WorkflowHost(ledger, lambda *_: None, lambda _: {"packaged": True})
    client = TestClient(create_app(host))
    snapshot = client.get(f"/api/v1/sessions/{session}/snapshot")
    assert snapshot.status_code == 200
    assert "pause" in snapshot.json()["allowed_actions"]
    replay = client.get(f"/api/v1/sessions/{session}/replay")
    assert replay.status_code == 200
    assert replay.json()["mode"] == "replay"
    assert replay.json()["events"][0]["payload"]["AWS_BEARER_TOKEN_BEDROCK"] == REDACTED
    artifact_response = client.get("/api/v1/artifacts/artifact-1").json()
    assert artifact_response["content"]["metric"] == 0.6
    assert artifact_response["content"]["github_token"] == REDACTED
    sequence = snapshot.json()["latest_sequence"]
    accepted = client.post(f"/api/v1/sessions/{session}/pause", json={"expected_sequence": sequence})
    assert accepted.status_code == 200
    stale = client.post(f"/api/v1/sessions/{session}/resume", json={"expected_sequence": sequence})
    assert stale.status_code == 409


def test_redact_does_not_false_positive_on_token_count_fields() -> None:
    from flowstate.api.server import redact

    resources = {"bedrock_input_tokens": 6859, "bedrock_output_tokens": 9603, "wall_seconds": 74.4}
    result = redact(resources)

    assert result["bedrock_input_tokens"] == 6859
    assert result["bedrock_output_tokens"] == 9603
    assert redact("must-not-leak", key="AWS_BEARER_TOKEN_BEDROCK") == REDACTED
    assert redact("secret-value", key="github_token") == REDACTED


def test_delete_stopped_session_removes_session_scoped_history(tmp_path: Path) -> None:
    ledger = WorkflowLedger(tmp_path / "flowstate.sqlite3")
    session = ledger.create_session()
    ledger.set_session_status(session, ComponentStatus.FAILED)
    ledger.append_event(
        session_id=session, run_id="run", component_id="trainer", execution_id="exec",
        stage="training", event_type="failed", status=ComponentStatus.FAILED,
        plain_summary="Training failed", payload={},
    )
    host = WorkflowHost(ledger, lambda *_: None, lambda _: {"packaged": True})
    client = TestClient(create_app(host))

    response = client.delete(f"/api/v1/sessions/{session}")

    assert response.status_code == 204
    assert client.get(f"/api/v1/sessions/{session}/snapshot").status_code == 404
    assert client.get("/api/v1/sessions").json() == []


def test_delete_running_session_is_rejected(tmp_path: Path) -> None:
    class RunningTask:
        @staticmethod
        def done() -> bool:
            return False

    ledger = WorkflowLedger(tmp_path / "flowstate.sqlite3")
    session = ledger.create_session()
    ledger.set_session_status(session, ComponentStatus.RUNNING)
    host = WorkflowHost(ledger, lambda *_: None, lambda _: {"packaged": True})
    host.tasks[session] = RunningTask()  # type: ignore[assignment]
    client = TestClient(create_app(host))

    response = client.delete(f"/api/v1/sessions/{session}")

    assert response.status_code == 409
    assert response.json()["detail"] == "Stop the running session before deleting it"
    assert client.get(f"/api/v1/sessions/{session}/snapshot").status_code == 200


def test_cancel_stops_task_and_allows_immediate_delete(tmp_path: Path) -> None:
    class CancellableTask:
        cancelled = False

        def done(self) -> bool:
            return self.cancelled

        def cancel(self) -> None:
            self.cancelled = True

    ledger = WorkflowLedger(tmp_path / "flowstate.sqlite3")
    session = ledger.create_session()
    ledger.set_session_status(session, ComponentStatus.RUNNING)
    task = CancellableTask()
    host = WorkflowHost(ledger, lambda *_: None, lambda _: {"packaged": True})
    host.tasks[session] = task  # type: ignore[assignment]
    client = TestClient(create_app(host))
    sequence = client.get(f"/api/v1/sessions/{session}/snapshot").json()["latest_sequence"]

    cancelled = client.post(
        f"/api/v1/sessions/{session}/cancel",
        json={"expected_sequence": sequence},
    )

    assert cancelled.status_code == 200
    assert task.cancelled is True
    snapshot = client.get(f"/api/v1/sessions/{session}/snapshot").json()
    assert snapshot["cancelled"] is True
    assert snapshot["allowed_actions"] == []
    assert client.delete(f"/api/v1/sessions/{session}").status_code == 204
    assert client.get(f"/api/v1/sessions/{session}/snapshot").status_code == 404


def test_final_package_files_are_downloadable_only_from_finalized_directory(tmp_path: Path) -> None:
    ledger = WorkflowLedger(tmp_path / "flowstate.sqlite3")
    session = ledger.create_session()
    package = tmp_path / "final" / session
    package.mkdir(parents=True)
    manifest = package / "manifest.json"
    predictions = package / "predictions.csv"
    manifest.write_text('{"validation_best":"B0"}\n', encoding="utf-8")
    predictions.write_text("row_id,user_id,video_id,score\n0,u,v,0.5\n", encoding="utf-8")
    with ledger.transaction() as connection:
        connection.execute(
            "INSERT INTO finalizations VALUES(?,?,?,?)",
            (session, "manifest-hash", str(manifest), "2026-08-31T00:00:00+00:00"),
        )
    client = TestClient(
        create_app(WorkflowHost(ledger, lambda *_: None, lambda _: {"packaged": True}))
    )

    csv_response = client.get(f"/api/v1/sessions/{session}/package/predictions.csv")
    manifest_response = client.get(f"/api/v1/sessions/{session}/package/manifest.json")

    assert csv_response.status_code == 200
    assert csv_response.headers["content-disposition"] == 'attachment; filename="predictions.csv"'
    assert csv_response.text.startswith("row_id,user_id,video_id,score")
    assert manifest_response.status_code == 200
    assert manifest_response.json()["validation_best"] == "B0"
    assert client.get(f"/api/v1/sessions/{session}/package/checkpoint.pt").status_code == 404
