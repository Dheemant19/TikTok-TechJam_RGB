from __future__ import annotations

import json
from pathlib import Path

from rigor_rs.contract.challenge import load_challenge_contract
from rigor_rs.contract.models import ComponentStatus
from rigor_rs.ledger.workflow import WorkflowLedger


def test_challenge_contract_derives_official_values() -> None:
    contract = load_challenge_contract()
    assert contract.label == "long_view"
    assert contract.metrics == ["GAUC", "nDCG@5"]
    assert contract.convergence_epsilon == 0.002
    assert contract.convergence_patience == 3
    assert contract.submission_header == ["row_id", "user_id", "video_id", "score"]
    assert not contract.allow_test_labels_during_development
    contract.verify_hashes()


def test_ledger_is_append_only_hash_chained_and_replayable(tmp_path: Path) -> None:
    ledger = WorkflowLedger(tmp_path / "rigor.sqlite3")
    session = ledger.create_session()
    first = ledger.append_event(
        session_id=session, run_id="B0", component_id="trainer", execution_id="exec-1",
        stage="baseline", event_type="started", status=ComponentStatus.RUNNING,
        plain_summary="Baseline started",
    )
    second = ledger.append_event(
        session_id=session, run_id="B0", component_id="evaluator", execution_id="exec-2",
        stage="validation", event_type="metric", status=ComponentStatus.SUCCEEDED,
        plain_summary="Metric recorded", payload={"metrics": {"primary": 0.6}},
    )
    assert first.sequence == 1 and second.sequence == 2
    assert second.previous_event_hash == first.event_hash
    assert ledger.verify_chain(session)
    snapshot = ledger.snapshot(session)
    assert snapshot.latest_sequence == 2
    assert snapshot.metrics["primary"] == 0.6
    assert [event.event_id for event in ledger.events(session, after_sequence=1)] == [second.event_id]

def test_component_events_do_not_overwrite_workflow_lifecycle(tmp_path: Path) -> None:
    ledger = WorkflowLedger(tmp_path / "rigor.sqlite3")
    session = ledger.create_session()
    ledger.set_session_status(session, ComponentStatus.RUNNING)
    ledger.append_event(
        session_id=session, run_id="run", component_id="data_profiler", execution_id="profile",
        stage="profile", event_type="completed", status=ComponentStatus.SUCCEEDED,
        plain_summary="Profile completed",
    )

    snapshot = ledger.snapshot(session)
    assert snapshot.status == ComponentStatus.RUNNING
    assert snapshot.component_states["data_profiler"] == ComponentStatus.SUCCEEDED
    assert snapshot.allowed_actions == ["pause", "cancel"]

    ledger.set_session_status(session, ComponentStatus.SUCCEEDED)
    assert ledger.snapshot(session).status == ComponentStatus.SUCCEEDED


def test_manual_interventions_are_recorded_and_counted(tmp_path: Path) -> None:
    # The count was previously always 0: nothing ever wrote the
    # manual_interventions table, so "zero human intervention" was an
    # unverifiable claim. Pause/resume/cancel are the explicit policy.
    ledger = WorkflowLedger(tmp_path / "rigor.sqlite3")
    session = ledger.create_session()
    ledger.set_session_status(session, ComponentStatus.RUNNING)
    assert ledger.snapshot(session).manual_interventions == 0

    accepted, _ = ledger.control(session, "pause", ledger.snapshot(session).latest_sequence)
    assert accepted
    assert ledger.manual_intervention_count(session) == 1

    accepted, _ = ledger.control(session, "resume", ledger.snapshot(session).latest_sequence)
    assert accepted
    snapshot = ledger.snapshot(session)
    assert snapshot.manual_interventions == 2
    assert snapshot.status == ComponentStatus.RUNNING

    with ledger.connect() as connection:
        rows = connection.execute(
            "SELECT action FROM manual_interventions WHERE session_id=? ORDER BY occurred_at", (session,)
        ).fetchall()
    assert [row["action"] for row in rows] == ["pause", "resume"]
