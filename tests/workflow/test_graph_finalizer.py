from __future__ import annotations

import asyncio
from pathlib import Path
import time
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from rigor_rs.contract.challenge import load_challenge_contract
from rigor_rs.contract.models import ComponentStatus, FrontierState
from rigor_rs.ledger.workflow import WorkflowLedger
from rigor_rs.models.experimental import FactorizationMachine
from rigor_rs.orchestration.graph import AutonomousResearchWorkflow
from rigor_rs.reporting.finalizer import SubmissionFinalizer


def test_langgraph_contains_durable_research_loop() -> None:
    workflow = AutonomousResearchWorkflow(SimpleNamespace())
    nodes = set(workflow.graph.get_graph().nodes)
    assert {"prepare", "profile", "baseline", "research", "code", "execute", "evaluate", "decide", "recover"} <= nodes


@pytest.mark.asyncio
async def test_baseline_training_keeps_event_loop_responsive(tmp_path: Path, monkeypatch) -> None:
    def reproduce(_transform_dir):
        time.sleep(0.2)
        return {"status": "succeeded", "seeds": [{"metrics": {"primary": 0.6}}]}

    services = SimpleNamespace(
        baseline=SimpleNamespace(reproduce=reproduce),
        frontier=SimpleNamespace(
            register_baseline=lambda _run_id: SimpleNamespace(
                model_dump=lambda mode: {"validation_best": "B0"}
            )
        ),
    )
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(workflow, "_event", lambda *args, **kwargs: None)

    started = time.perf_counter()
    task = asyncio.create_task(
        workflow.baseline({"session_id": "session", "transform_dir": str(tmp_path)})
    )
    await asyncio.sleep(0.02)

    assert time.perf_counter() - started < 0.1
    assert not task.done()
    assert (await task)["baseline_result"]["status"] == "succeeded"


def test_finalization_is_one_way(tmp_path: Path, monkeypatch) -> None:
    ledger = WorkflowLedger(tmp_path / "rigor.sqlite3")
    session = ledger.create_session()
    transform = tmp_path / "transform"; transform.mkdir()
    (transform / "transform_state.json").write_text("{}", encoding="utf-8")
    ledger.append_event(
        session_id=session, run_id="workflow", component_id="data_profiler", execution_id="profile",
        stage="profile", event_type="completed", status=ComponentStatus.SUCCEEDED,
        plain_summary="profiled", payload={"transform": {"receipt": {"path": str(transform / "transform_receipt.json")}}},
    )
    frontier = FrontierState(validation_best="run-1", stable_fallback="run-1", accepted_parent="run-1", locked=True)
    ledger.append_event(
        session_id=session, run_id="run-1", component_id="watchdog", execution_id="decision",
        stage="decision", event_type="frontier", status=ComponentStatus.SUCCEEDED,
        plain_summary="stopped", payload={"frontier": frontier.model_dump(mode="json"), "experiment_id": "E1"},
    )
    artifacts = tmp_path / "artifacts"
    checkpoint = artifacts / "runs/E1/tier4/model/checkpoint.pt"; checkpoint.parent.mkdir(parents=True)
    model = FactorizationMachine(20, 4)
    torch.save({"state_dict": model.state_dict(), "dimension": 20, "config": {"model": {"factors": 4}}}, checkpoint)
    finalizer = SubmissionFinalizer(load_challenge_contract(), ledger, artifacts)
    monkeypatch.setattr(finalizer, "_test_features", lambda _: (np.asarray([[1, 2, 3, 4, 5]], dtype=np.int32), ["u"], ["v"]))
    monkeypatch.setattr("rigor_rs.reporting.finalizer.subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="ok", stderr=""))
    result = finalizer.package(session)
    assert result["test_prediction_passes"] == 1
    assert result["event_chain_valid"]
    with pytest.raises(RuntimeError, match="already been finalized"):
        finalizer.package(session)
