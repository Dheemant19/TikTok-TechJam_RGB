from __future__ import annotations

from pathlib import Path

from rigor_rs.contract.challenge import load_challenge_contract
from rigor_rs.contract.models import MetricReceipt
from rigor_rs.integrity.gates import evaluator_metamorphic_checks
from rigor_rs.ledger.workflow import canonical_hash
from rigor_rs.orchestration.frontier import FrontierManager
from rigor_rs.recovery.controller import RecoveryController


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
