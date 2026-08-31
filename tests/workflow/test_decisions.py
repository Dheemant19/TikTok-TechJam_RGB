from __future__ import annotations

from pathlib import Path

from flowstate.contract.challenge import load_challenge_contract
from flowstate.contract.models import MetricReceipt
from flowstate.integrity.gates import evaluator_metamorphic_checks
from flowstate.ledger.workflow import WorkflowLedger, canonical_hash
from flowstate.orchestration.frontier import FrontierManager
from flowstate.recovery.controller import RecoveryController


def metric(run_id: str, primary: float, comparable: bool = True, scope: str = "validation") -> MetricReceipt:
    document = {
        "receipt_id": f"metric-{run_id}", "run_id": run_id, "prediction_artifact_id": "memory",
        "evaluator_hash": "a" * 64, "config_hash": "b" * 64,
        "gauc": primary, "ndcg_at_5": primary, "primary": primary,
        "users": 2, "rows": 4, "comparable": comparable, "scope": scope,
    }
    return MetricReceipt(**document, receipt_hash=canonical_hash(document))


def test_official_evaluator_metamorphic_contracts() -> None:
    assert all(evaluator_metamorphic_checks(load_challenge_contract()).values())


def test_convergence_counts_only_comparable_full_validation() -> None:
    manager = FrontierManager(epsilon=0.002, patience=3)
    state = manager.register_baseline("B0")
    best = parent = metric("B0", 0.60)
    proxy = metric("proxy", 0.99, comparable=False, scope="proxy")
    state, decision, stop = manager.decide(state, proxy, "proxy", best, parent)
    assert state.no_improvement_count == 0 and not stop
    for index, value in enumerate((0.601, 0.6015, 0.6019), start=1):
        state, decision, stop = manager.decide(state, metric(f"E{index}", value), f"E{index}", best, parent)
    assert stop
    assert state.validation_best == "B0"
    assert state.no_improvement_count == 3



def test_duplicate_predictions_are_rejected_not_marked_ambiguous() -> None:
    manager = FrontierManager(epsilon=0.002, patience=3)
    state = manager.register_baseline("B0")
    baseline = metric("B0", 0.60)
    duplicate = metric("E2", 0.6019)

    updated, decision, stop = manager.decide(
        state,
        duplicate,
        "E2",
        baseline,
        baseline,
        duplicate_of_run_id="E1",
    )

    assert decision == "reject"
    assert updated.rejected == ["E2"]
    assert updated.no_improvement_count == 0
    assert not stop


def test_ledger_finds_prior_run_with_identical_predictions(tmp_path: Path) -> None:
    ledger = WorkflowLedger(tmp_path / "flowstate.sqlite3")
    session_id = ledger.create_session()
    first = metric("E1", 0.601).model_dump(mode="json")
    second = metric("E2", 0.602).model_dump(mode="json")
    second["prediction_artifact_id"] = first["prediction_artifact_id"]

    ledger.store_metric_receipt(session_id, "E1", first)

    assert ledger.prior_run_for_prediction(
        session_id,
        second["prediction_artifact_id"],
        "E2",
    ) == "E1"

def test_recovery_recipes_are_bounded() -> None:
    controller = RecoveryController()
    first = controller.recover("run", "CUDA out of memory", 1, 2)
    third = controller.recover("run", "CUDA out of memory", 3, 2)
    regression = controller.recover("run", "metric regression", 1, 2)
    assert first.action == "halve_micro_batch"
    assert third.result == "recovery cap exhausted"
    assert regression.result == "reject experiment"


def test_truncated_agent_json_uses_agent_output_recovery() -> None:
    receipt = RecoveryController().recover(
        "run",
        "Invalid JSON: EOF while parsing a value [type=json_invalid]",
        1,
        2,
    )

    assert receipt.category == "agent_output"
    assert receipt.action == "bounded_structured_output_retry"


def test_invalid_diff_uses_code_patch_recovery() -> None:
    receipt = RecoveryController().recover(
        "run",
        "patch contains no file changes",
        1,
        2,
    )

    assert receipt.category == "code_patch"
    assert receipt.action == "regenerate_standard_git_diff"


def test_hallucinated_citation_uses_agent_output_recovery() -> None:
    receipt = RecoveryController().recover(
        "run",
        "Research Agent cited evidence not supplied by MCP",
        1,
        1,
    )

    assert receipt.category == "agent_output"
    assert receipt.action == "bounded_structured_output_retry"
    assert receipt.result == "retry permitted"


def test_inert_patch_uses_behavior_unchanged_recovery() -> None:
    receipt = RecoveryController().recover(
        "run",
        "patch produced no measurable change in ranking behavior: proxy-scale "
        "within-user validation ordering is identical to the unpatched experiment baseline",
        1,
        2,
    )

    assert receipt.category == "behavior_unchanged"
    assert receipt.action == "activate_new_capability_in_config_or_callsites"
    assert receipt.result == "retry permitted"


def test_python_traceback_uses_code_patch_recovery() -> None:
    receipt = RecoveryController().recover(
        "run", "TypeError: unsupported operand type in agent-generated training code", 1, 2
    )

    assert receipt.category == "code_patch"
    assert receipt.action == "regenerate_standard_git_diff"
