from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from rigor_rs.api.server import REDACTED, WorkflowHost, create_app
from rigor_rs.contract.models import ArtifactRef, ComponentStatus
from rigor_rs.ledger.workflow import WorkflowLedger


def test_snapshot_replay_controls_and_artifact_redaction(tmp_path: Path) -> None:
    ledger = WorkflowLedger(tmp_path / "rigor.sqlite3")
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
    from rigor_rs.api.server import redact

    resources = {"bedrock_input_tokens": 6859, "bedrock_output_tokens": 9603, "wall_seconds": 74.4}
    result = redact(resources)

    assert result["bedrock_input_tokens"] == 6859
    assert result["bedrock_output_tokens"] == 9603
    assert redact("must-not-leak", key="AWS_BEARER_TOKEN_BEDROCK") == REDACTED
    assert redact("secret-value", key="github_token") == REDACTED
