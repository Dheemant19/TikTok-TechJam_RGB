from __future__ import annotations

import asyncio
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import torch

from flowstate.contract.challenge import load_challenge_contract
from flowstate.contract.models import ComponentStatus, FrontierState, MetricReceipt
from flowstate.knowledge.models import EvidenceFilters
from flowstate.ledger.workflow import WorkflowLedger
from flowstate.models.experimental import FactorizationMachine
from flowstate.orchestration.graph import AutonomousResearchWorkflow
from flowstate.recovery.controller import RecoveryController
from flowstate.reporting.finalizer import SubmissionFinalizer


def test_langgraph_contains_durable_research_loop() -> None:
    workflow = AutonomousResearchWorkflow(SimpleNamespace())
    nodes = set(workflow.graph.get_graph().nodes)
    assert {"prepare", "profile", "baseline", "research", "code", "execute", "evaluate", "decide", "recover"} <= nodes


def test_training_entrypoint_guard_rejects_truncated_valid_python(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    experiment = workspace / "src/flowstate/training/experiment.py"
    experiment.parent.mkdir(parents=True)
    experiment.write_text(
        "def train():\n"
        "    checkpoint = 'checkpoint.pt'\n"
        "    scores = 'valid_scores.npy'\n"
        "    receipt = 'train_receipt.json'\n",
        encoding="utf-8",
    )
    reverted = {"value": False}
    workflow = AutonomousResearchWorkflow(
        SimpleNamespace(
            workspace=SimpleNamespace(
                revert=lambda _workspace: reverted.__setitem__("value", True)
            )
        )
    )

    with pytest.raises(ValueError, match="missing top-level functions.*main"):
        workflow._verify_training_entrypoint(workspace)

    assert reverted["value"]


def test_training_entrypoint_guard_accepts_executable_contract(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    experiment = workspace / "src/flowstate/training/experiment.py"
    experiment.parent.mkdir(parents=True)
    experiment.write_text(
        "def train():\n"
        "    return ('checkpoint.pt', 'valid_scores.npy', 'train_receipt.json')\n\n"
        "def predict():\n"
        "    return '--predict-data'\n\n"
        "def main():\n"
        "    train()\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    workflow = AutonomousResearchWorkflow(
        SimpleNamespace(
            workspace=SimpleNamespace(
                revert=lambda _workspace: pytest.fail("valid entrypoint must not revert")
            )
        )
    )

    workflow._verify_training_entrypoint(workspace)


@pytest.mark.asyncio
async def test_prepare_bootstraps_curated_code_bank_under_training_data(tmp_path: Path) -> None:
    # Every research() call now requires cited evidence to carry verified
    # code; the curated bank is the only source guaranteed to be present
    # before the very first research() call (live Hugging Face Papers
    # discovery is hard-checked per-experiment instead), so prepare() must
    # resolve it once, up front -- not leave it as a manual CLI step nobody
    # ran. Logged under `train_data` -- this is still data preparation, so
    # it groups with "Training and validation data contract locked" in the
    # Autonomy Log -- and never under `ledger` ("Save Run Evidence"), whose
    # own real "Succeeded" status only ever fires much later when B0 is
    # registered as the frontier baseline (the exact premature-status bug
    # just fixed for Check Data Safety, now avoided here too).
    from flowstate.knowledge.config import repository_root
    from flowstate.knowledge.models import IngestionReceipt

    ledger = WorkflowLedger(tmp_path / "flowstate.sqlite3")
    session_id = ledger.create_session()
    calls = {"count": 0}

    async def fake_ensure_curated_bank() -> list[IngestionReceipt]:
        calls["count"] += 1
        return [IngestionReceipt(
            receipt_id="ing-test", paper_id="arxiv:bpr", work_key="arxiv:bpr",
            source="curated", outcome="updated", content_hash="a" * 64,
        )]

    services = SimpleNamespace(
        contract=load_challenge_contract(),
        repository=repository_root(),
        ledger=ledger,
        knowledge=SimpleNamespace(ingestion=SimpleNamespace(ensure_curated_bank=fake_ensure_curated_bank)),
    )
    workflow = AutonomousResearchWorkflow(services)

    result = await workflow.prepare({"session_id": session_id, "run_id": "workflow"})

    assert calls["count"] == 1
    assert result["status"] == "running"
    bank_events = [event for event in ledger.events(session_id) if event.event_type == "curated_bank_ready"]
    assert len(bank_events) == 1
    assert bank_events[0].component_id == "train_data"
    assert bank_events[0].payload["receipts"][0]["paper_id"] == "arxiv:bpr"


@pytest.mark.asyncio
async def test_behavior_unchanged_vs_baseline_detects_dead_patches_and_caches_reference_run(tmp_path: Path) -> None:
    # Reproduced live: a patch can add a real, working model/loss capability
    # that compiles, passes tests, and trains, but is never actually wired
    # into train()'s call sites (e.g. training.loss never flipped in the
    # experiment config, or a new constructor kwarg never passed). Three
    # separate experiments this way produced bit-identical metrics. This
    # check compares each experiment's proxy-scale scores against a lazily
    # computed, session-cached reference run of the unpatched baseline.
    transform_dir = tmp_path / "transform"
    transform_dir.mkdir()
    reference_scores = np.asarray([0.1, 0.2, 0.3], dtype=np.float32)
    np.savez_compressed(
        transform_dir / "valid.npz",
        users=np.asarray(["u1", "u1", "u1"]),
    )

    tier2_calls = []

    class FakeWorkspace:
        def create(self, experiment_id, parent, **_kwargs):
            return tmp_path / "reference_workspace", "commit-hash"

    class FakeFunnel:
        async def tier2(self, workspace, transform_dir, config, output, seed):
            tier2_calls.append((workspace, seed))
            model_dir = output / "model"
            model_dir.mkdir(parents=True, exist_ok=True)
            np.save(model_dir / "valid_scores.npy", reference_scores)
            return SimpleNamespace(status="succeeded")

    services = SimpleNamespace(workspace=FakeWorkspace(), funnel=FakeFunnel(), artifacts=tmp_path / "artifacts")
    workflow = AutonomousResearchWorkflow(services)

    dead_patch_output = tmp_path / "dead_patch" / "tier2"
    (dead_patch_output / "model").mkdir(parents=True)
    np.save(dead_patch_output / "model" / "valid_scores.npy", reference_scores.copy())

    real_patch_output = tmp_path / "real_patch" / "tier2"
    (real_patch_output / "model").mkdir(parents=True)
    np.save(real_patch_output / "model" / "valid_scores.npy", np.asarray([0.9, 0.8, 0.7], dtype=np.float32))

    assert await workflow._behavior_unchanged_vs_baseline("session-1", transform_dir, dead_patch_output, 0) is True
    assert await workflow._behavior_unchanged_vs_baseline("session-1", transform_dir, real_patch_output, 0) is False
    # The reference run must be computed exactly once and reused for both checks.
    assert len(tier2_calls) == 1

def test_ranking_guard_rejects_different_scores_with_identical_within_user_order() -> None:
    users = np.asarray(["u1", "u1", "u2", "u2"])
    baseline = np.asarray([0.1, 0.2, -2.0, 4.0])
    monotonic_rescale = np.asarray([10.0, 20.0, -20.0, 40.0])
    changed_ranking = np.asarray([20.0, 10.0, -20.0, 40.0])

    assert AutonomousResearchWorkflow._same_within_user_ranking(
        users, baseline, monotonic_rescale
    )
    assert not AutonomousResearchWorkflow._same_within_user_ranking(
        users, baseline, changed_ranking
    )


@pytest.mark.asyncio
async def test_execute_short_circuits_before_expensive_tiers_on_dead_patch(tmp_path: Path, monkeypatch) -> None:
    from flowstate.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches, PatchProposal

    contract = ExperimentContract(experiment_id="E1", parent_run_id="B0", hypothesis="Pairwise BPR ranking loss for long_view",
    observed_evidence_ids=[], primary_change="swap to BPR", allowed_files=["src/flowstate/training/experiment.py", "configs/experiments/candidate.yaml"], prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
    falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
    comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
    budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
    fallback_run_id="B0", recovery_attempt_limit=1,)
    proposal = PatchProposal(unified_diff="diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n", tests=[], explanation="x")

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tier3_called = {"value": False}
    scores = np.asarray([0.1, 0.2, 0.3], dtype=np.float32)
    transform_dir = tmp_path / "transform"
    transform_dir.mkdir()
    np.savez_compressed(
        transform_dir / "valid.npz",
        users=np.asarray(["u1", "u1", "u1"]),
    )

    class FakeFunnel:
        async def tier1(self, *_a, **_k):
            return SimpleNamespace(status="succeeded", model_dump=lambda mode: {}, error=None)

        async def tier2(self, workspace, transform_dir, config, output, seed):
            model_dir = output / "model"
            model_dir.mkdir(parents=True, exist_ok=True)
            np.save(model_dir / "valid_scores.npy", scores)
            (model_dir / "train_receipt.json").write_text(
                '{"model_family":"factorization_machine","uses_chronological_history":false,"auxiliary_heads":[]}',
                encoding="utf-8",
            )
            return SimpleNamespace(status="succeeded", model_dump=lambda mode: {}, error=None)

        async def tier3(self, *_a, **_k):
            tier3_called["value"] = True
            return SimpleNamespace(status="succeeded", model_dump=lambda mode: {}, error=None)

    class FakeWorkspace:
        def create(self, experiment_id, parent, **_kwargs):
            return tmp_path / "reference_workspace", "commit-hash"

    services = SimpleNamespace(
        workspace=FakeWorkspace(), funnel=FakeFunnel(), artifacts=tmp_path / "artifacts",
    )
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(workflow, "_event", lambda *args, **kwargs: None)

    state = {
        "session_id": "session-1", "experiment_contract": contract.model_dump(mode="json"),
        "patch_proposal": proposal.model_dump(mode="json"), "workspace": str(workspace),
        "touched_files": ["a.py"], "transform_dir": str(transform_dir),
    }

    result = await workflow.execute(state)

    assert not tier3_called["value"]
    assert "no measurable change in ranking behavior" in result["error"]


@pytest.mark.asyncio
async def test_execute_contains_unhandled_exceptions_as_recoverable_errors(tmp_path: Path, monkeypatch) -> None:
    # An unhandled exception in the funnel (live: a SyntaxError raised by
    # tier1's bare compile() on agent-generated code) previously escaped this
    # graph node entirely -- LangGraph recorded an internal __error__ write and
    # the whole run died with no ledger event, no recovery, and no visible
    # failure. It must become a routed, recoverable error instead.
    from flowstate.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches, PatchProposal

    contract = ExperimentContract(experiment_id="E1", parent_run_id="B0", hypothesis="Pairwise BPR ranking loss for long_view",
    observed_evidence_ids=[], primary_change="swap to BPR", allowed_files=["src/flowstate/training/experiment.py", "configs/experiments/candidate.yaml"], prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
    falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
    comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
    budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
    fallback_run_id="B0", recovery_attempt_limit=1,)
    proposal = PatchProposal(unified_diff="diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n", tests=[], explanation="x")

    class ExplodingFunnel:
        async def tier1(self, *_a, **_k):
            raise SyntaxError("unterminated string literal (detected at line 229)")

    services = SimpleNamespace(
        funnel=ExplodingFunnel(), artifacts=tmp_path / "artifacts",
        recovery=RecoveryController(),
    )
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(workflow, "_event", lambda *args, **kwargs: None)

    state = {
        "session_id": "session-1", "experiment_contract": contract.model_dump(mode="json"),
        "patch_proposal": proposal.model_dump(mode="json"), "workspace": str(tmp_path),
        "touched_files": ["a.py"], "transform_dir": str(tmp_path / "transform"),
    }

    result = await workflow.execute(state)

    assert "SyntaxError" in result["error"]
    # Must route into recovery, and classify to the code-repair recipe.
    assert workflow._route_execute(result) == "recover"
    assert RecoveryController().classify(result["error"]) == "syntax_import_config"


def test_recover_node_has_outgoing_edges_back_into_the_loop() -> None:
    # _route_recovery existed but _build() never wired it via
    # add_conditional_edges("recover", ...), so every recovery event -- a
    # hallucinated citation, a timeout, any transient failure -- silently
    # terminated the whole workflow instead of retrying, with no error and
    # no way to tell the difference from a legitimate stop.
    workflow = AutonomousResearchWorkflow(SimpleNamespace())
    edges = {(edge.source, edge.target) for edge in workflow.graph.get_graph().edges}
    assert ("recover", "research") in edges
    assert ("recover", "__end__") in edges
    # Code-level failures retry the patch for the same contract.
    assert ("recover", "code") in edges
    # Byte-identical full-validation predictions are implementation failures,
    # so evaluation must be able to recover instead of counting convergence.
    assert ("evaluate", "recover") in edges
    assert ("evaluate", "decide") in edges


def test_activation_selects_the_loss_branch_the_patch_introduced(tmp_path: Path) -> None:
    # Observed live on every cycle: the agent implemented a real BPR loss behind
    # a brand-new `loss_name == "bpr_longview"` branch while leaving
    # configs/experiments/candidate.yaml at loss: bce, so the new code was
    # unreachable. Two rounds of explicit prompting plus feeding the exact
    # diagnosis back did not stop it, so the switch is thrown deterministically.
    workspace = tmp_path / "ws"
    (workspace / "src/flowstate/training").mkdir(parents=True)
    (workspace / "configs/experiments").mkdir(parents=True)
    experiment = workspace / "src/flowstate/training/experiment.py"
    config = workspace / "configs/experiments/candidate.yaml"

    head_source = 'if loss_name == "bpr":\n    pass\n'
    experiment.write_text('if loss_name == "bpr_longview":\n    pass\n', encoding="utf-8")
    config.write_text("# keep this comment\ntraining:\n  loss: bce\n  epochs: 20\n", encoding="utf-8")

    services = SimpleNamespace(workspace=SimpleNamespace(
        file_at_head=lambda _ws, _rel: head_source,
        revert=lambda _ws: pytest.fail("an unambiguous activation must not revert"),
    ))
    workflow = AutonomousResearchWorkflow(services)

    assert workflow._activate_patch_capability(workspace, head_source) == "bpr_longview"
    updated = config.read_text(encoding="utf-8")
    assert "loss: bpr_longview" in updated
    # Comments and sibling keys must survive the in-place edit.
    assert "# keep this comment" in updated
    assert "epochs: 20" in updated

    # Already-selected: nothing further to do.
    assert workflow._activate_patch_capability(workspace, head_source) is None


def test_activation_ignores_patches_that_add_no_loss_branch(tmp_path: Path) -> None:
    # A pure architecture change must not be touched just because HEAD already
    # carries its own already-unselected branch.
    workspace = tmp_path / "ws2"
    (workspace / "src/flowstate/training").mkdir(parents=True)
    (workspace / "configs/experiments").mkdir(parents=True)
    source = 'if loss_name == "bpr":\n    pass\n'
    (workspace / "src/flowstate/training/experiment.py").write_text(source, encoding="utf-8")
    config = workspace / "configs/experiments/candidate.yaml"
    config.write_text("training:\n  loss: bce\n", encoding="utf-8")

    services = SimpleNamespace(workspace=SimpleNamespace(
        file_at_head=lambda _ws, _rel: source,
        revert=lambda _ws: pytest.fail("must not revert an unrelated patch"),
    ))
    workflow = AutonomousResearchWorkflow(services)

    assert workflow._activate_patch_capability(workspace, source) is None
    assert "loss: bce" in config.read_text(encoding="utf-8")


def test_activation_uses_agent_source_snapshot_not_stale_git_head(tmp_path: Path) -> None:
    workspace = tmp_path / "ws-uncommitted"
    (workspace / "src/flowstate/training").mkdir(parents=True)
    (workspace / "configs/experiments").mkdir(parents=True)
    existing_source = (
        'if loss_name == "bpr":\n'
        '    run_bpr()\n'
        'else:\n'
        '    run_bce()\n'
    )
    patched_source = existing_source.replace("run_bce()", "run_recency_weighted_bce()")
    (workspace / "src/flowstate/training/experiment.py").write_text(
        patched_source,
        encoding="utf-8",
    )
    config = workspace / "configs/experiments/candidate.yaml"
    config.write_text(
        "training:\n  loss: bce\n  recency_half_life_days: 7\n",
        encoding="utf-8",
    )
    workflow = AutonomousResearchWorkflow(
        SimpleNamespace(
            workspace=SimpleNamespace(
                file_at_head=lambda *_args: "",
                revert=lambda _workspace: pytest.fail("existing branch must not be activated"),
            )
        )
    )

    activated = workflow._activate_patch_capability(workspace, existing_source)

    assert activated is None
    assert "loss: bce" in config.read_text(encoding="utf-8")


def test_activation_raises_when_multiple_new_branches_are_ambiguous(tmp_path: Path) -> None:
    workspace = tmp_path / "ws3"
    (workspace / "src/flowstate/training").mkdir(parents=True)
    (workspace / "configs/experiments").mkdir(parents=True)
    (workspace / "src/flowstate/training/experiment.py").write_text(
        'if loss_name == "a":\n    pass\nif loss_name == "b":\n    pass\n', encoding="utf-8"
    )
    (workspace / "configs/experiments/candidate.yaml").write_text("training:\n  loss: bce\n", encoding="utf-8")

    reverted = {"value": False}
    services = SimpleNamespace(workspace=SimpleNamespace(
        file_at_head=lambda _ws, _rel: "",
        revert=lambda _ws: reverted.__setitem__("value", True),
    ))
    workflow = AutonomousResearchWorkflow(services)

    with pytest.raises(ValueError, match="ambiguous activation"):
        workflow._activate_patch_capability(workspace, "")
    assert reverted["value"], "must revert so the repaired patch still applies"


def _minimal_contract(allowed_files: list[str]):
    from flowstate.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches
    return ExperimentContract(
        experiment_id="E1", parent_run_id="B0", hypothesis="Some sufficiently long hypothesis text for validation",
        observed_evidence_ids=[], primary_change="test change", allowed_files=allowed_files,
        prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
        falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
        comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
        budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
        fallback_run_id="B0", recovery_attempt_limit=2,
    )

def _policy_workflow() -> AutonomousResearchWorkflow:
    services = SimpleNamespace(
        research_strategy={
            "fm_choosing_score": 0.15,
            "fm_family_names": [
                "factorization_machine",
                "fm",
                "deepfm",
                "deep_factorization_machine",
            ],
            "minimum_non_fm_between_fm": 3,
            "require_non_fm_first": False,
            "semantic_duplicate_similarity": 0.72,
            "innovation_minimum_delta_vs_baseline": 0.0,
            "ensemble_minimum_delta_vs_best": 0.002,
            "minimum_eligible_models_for_ensemble": 2,
        },
        contract=SimpleNamespace(baseline_valid={"primary": 0.6016}),
    )
    return AutonomousResearchWorkflow(services)


def test_fm_family_requires_three_non_fm_experiments_between_attempts() -> None:
    workflow = _policy_workflow()
    first = workflow._research_diversity_policy([])
    blocked = workflow._research_diversity_policy([
        {"method_family": "factorization_machine", "mechanism_id": "fm_bpr"},
        {"method_family": "din", "mechanism_id": "din_bpr"},
        {"method_family": "mmoe", "mechanism_id": "mmoe_bpr"},
    ])
    allowed = workflow._research_diversity_policy([
        {"method_family": "factorization_machine", "mechanism_id": "fm_bpr"},
        {"method_family": "din", "mechanism_id": "din_bpr"},
        {"method_family": "mmoe", "mechanism_id": "mmoe_bpr"},
        {"method_family": "dcnv2", "mechanism_id": "dcnv2_bpr"},
    ])
    deepfm_blocked = workflow._research_diversity_policy([
        {"method_family": "deepfm", "mechanism_id": "deepfm_bce"},
    ])
    initial_fm_allowed = workflow._research_diversity_policy([
        {"method_family": "din", "mechanism_id": "din_bpr"},
        {"method_family": "ple", "mechanism_id": "ple_bpr"},
        {"method_family": "dcnv2", "mechanism_id": "dcnv2_bpr"},
    ])
    repeated_family = workflow._research_diversity_policy([
        {"method_family": "din", "mechanism_id": "din_bpr"},
        {"method_family": "mmoe", "mechanism_id": "mmoe_bce"},
        {"method_family": "mmoe", "mechanism_id": "mmoe_mgda"},
    ])

    assert first["fm_family_allowed"] is True
    assert blocked["required_model_scope"] == "non_fm"
    assert blocked["non_fm_experiments_since_last_fm"] == 2
    assert allowed["fm_family_allowed"] is True
    assert initial_fm_allowed["fm_family_allowed"] is True
    assert deepfm_blocked["fm_family_allowed"] is False
    assert repeated_family["blocked_model_families"] == ["mmoe"]


def test_semantic_duplicate_blocks_renamed_hypothesis_but_allows_one_exact_tuning_round() -> None:
    workflow = _policy_workflow()
    previous = {
        "mechanism_id": "din_history_bpr",
        "hypothesis": "DIN chronological history attention improves within-user ranking",
        "primary_change": "Add chronological history attention with BPR loss",
    }
    renamed = _minimal_contract(["src/flowstate/training/experiment.py"]).model_copy(update={
        "hypothesis": "Chronological history attention in DIN improves within-user ranking",
        "primary_change": "Use BPR loss with chronological history attention",
        "mechanism_id": "din_attention_pairwise_v2",
        "method_family": "din",
    })
    tuning = renamed.model_copy(update={
        "mechanism_id": "din_history_bpr",
        "iteration_strategy": "tune_current_model",
    })

    duplicate, similarity = workflow._semantic_duplicate(renamed, [previous])
    tuned_duplicate, _ = workflow._semantic_duplicate(tuning, [previous])

    assert duplicate == "din_history_bpr"
    assert similarity >= 0.72
    assert tuned_duplicate is None


def test_innovation_frontier_tracks_best_non_fm_above_baseline_only() -> None:
    workflow = _policy_workflow()
    frontier = workflow._innovation_frontier([
        {
            "run_id": "E1",
            "experiment_id": "E1",
            "method_family": "factorization_machine",
            "metrics": {"primary": 0.6040},
        },
        {
            "run_id": "E2",
            "experiment_id": "E2",
            "method_family": "din",
            "metrics": {"primary": 0.6020},
        },
        {
            "run_id": "E3",
            "experiment_id": "E3",
            "method_family": "dcnv2",
            "metrics": {"primary": 0.6010},
        },
    ])

    assert frontier["run_id"] == "E2"
    assert frontier["method_family"] == "din"
    assert frontier["eligible_for_final_artifact"] is False
    assert frontier["purpose"] == "innovation_story_only"


def test_ensemble_requires_non_fm_candidate_and_epsilon_sized_gain() -> None:
    workflow = _policy_workflow()
    weak_ensemble = _minimal_contract(["src/flowstate/models/candidate.py"]).model_copy(update={
        "implementation_kind": "ensemble",
        "method_family": "ensemble",
        "mechanism_id": "fm_din_score_blend",
        "minimum_primary_improvement": 0.0005,
    })
    policy = workflow._research_diversity_policy([])

    with pytest.raises(ValueError, match="2 distinct validated model families"):
        workflow._validate_ensemble_policy(weak_ensemble, {}, policy)

    policy["ensemble_candidates"] = [
        {"run_id": "E2", "method_family": "din", "primary": 0.602},
        {"run_id": "E3", "method_family": "dcnv2", "primary": 0.603},
    ]
    with pytest.raises(ValueError, match="validated non-FM innovation candidate"):
        workflow._validate_ensemble_policy(weak_ensemble, {}, policy)
    with pytest.raises(ValueError, match="at least 0.002 improvement"):
        workflow._validate_ensemble_policy(
            weak_ensemble,
            {"run_id": "E2", "method_family": "din", "primary": 0.602},
            policy,
        )

    qualifying = weak_ensemble.model_copy(update={"minimum_primary_improvement": 0.002})
    workflow._validate_ensemble_policy(
        qualifying,
        {"run_id": "E2", "method_family": "din", "primary": 0.602},
        policy,
    )


def test_ensemble_candidates_require_distinct_families_above_baseline() -> None:
    workflow = _policy_workflow()
    candidates = workflow._eligible_ensemble_candidates([
        {"run_id": "E1", "method_family": "din", "metrics": {"primary": 0.6020}},
        {"run_id": "E2", "method_family": "din", "metrics": {"primary": 0.6030}},
        {"run_id": "E3", "method_family": "dcnv2", "metrics": {"primary": 0.6010}},
        {"run_id": "E4", "method_family": "sasrec", "metrics": {"primary": 0.6040}},
    ])

    assert [(item["run_id"], item["method_family"]) for item in candidates] == [
        ("E4", "sasrec"),
        ("E2", "din"),
    ]

def test_new_symbol_wiring_check_rejects_a_class_train_never_calls(tmp_path: Path) -> None:
    # Reproduced from run-20260830T062501677461Z-e014e119 (EXP_mmoe_aux_longview_v1):
    # the Code Agent wrote a fully correct 66-line MMoEFactorizationMachine
    # class in models/experimental.py but never touched
    # training/experiment.py's model construction call site, so train()
    # kept building the old FactorizationMachine. A full tier2 GPU run then
    # discovered a bit-identical proxy ranking with only a generic error.
    # This must be caught immediately, for free, right after patch apply.
    workspace = tmp_path / "ws"
    (workspace / "src/flowstate/training").mkdir(parents=True)
    (workspace / "src/flowstate/models").mkdir(parents=True)
    (workspace / "src/flowstate/training/experiment.py").write_text(
        "from flowstate.models.experimental import FactorizationMachine\n"
        "def train():\n    model = FactorizationMachine()\n",
        encoding="utf-8",
    )
    (workspace / "src/flowstate/models/experimental.py").write_text(
        "class FactorizationMachine:\n    pass\n\n\nclass MMoEFactorizationMachine:\n    pass\n",
        encoding="utf-8",
    )
    contract = _minimal_contract(["src/flowstate/models/experimental.py", "src/flowstate/training/experiment.py"])

    reverted = {"value": False}
    services = SimpleNamespace(workspace=SimpleNamespace(
        file_at_head=lambda _ws, _rel: "class FactorizationMachine:\n    pass\n",
        revert=lambda _ws: reverted.__setitem__("value", True),
    ))
    workflow = AutonomousResearchWorkflow(services)

    with pytest.raises(ValueError, match="inert patch") as excinfo:
        workflow._verify_new_symbols_wired(workspace, contract)
    assert "MMoEFactorizationMachine" in str(excinfo.value)
    assert "src/flowstate/models/experimental.py" in str(excinfo.value)
    assert reverted["value"]
    # This exact wording must classify as behavior_unchanged, not infrastructure,
    # so the ledger routes it through the same bounded code retry as the tier2
    # variant instead of a generic infrastructure restart.
    message = f"ValueError: {excinfo.value}"
    assert RecoveryController.classify(message) == "behavior_unchanged"


def test_new_symbol_wiring_check_passes_when_train_references_the_new_class(tmp_path: Path) -> None:
    workspace = tmp_path / "ws2"
    (workspace / "src/flowstate/training").mkdir(parents=True)
    (workspace / "src/flowstate/models").mkdir(parents=True)
    (workspace / "src/flowstate/training/experiment.py").write_text(
        "from flowstate.models.experimental import MMoEFactorizationMachine\n"
        "def train():\n    model = MMoEFactorizationMachine()\n",
        encoding="utf-8",
    )
    (workspace / "src/flowstate/models/experimental.py").write_text(
        "class MMoEFactorizationMachine:\n    pass\n", encoding="utf-8",
    )
    contract = _minimal_contract(["src/flowstate/models/experimental.py", "src/flowstate/training/experiment.py"])

    services = SimpleNamespace(workspace=SimpleNamespace(
        file_at_head=lambda _ws, _rel: "",
        revert=lambda _ws: pytest.fail("a correctly wired patch must not revert"),
    ))
    workflow = AutonomousResearchWorkflow(services)

    workflow._verify_new_symbols_wired(workspace, contract)  # must not raise


def test_new_symbol_wiring_check_ignores_test_only_helpers(tmp_path: Path) -> None:
    # A helper class defined only for a unit test is not a training capability;
    # it must not be flagged just because train() never calls it.
    workspace = tmp_path / "ws3"
    (workspace / "src/flowstate/training").mkdir(parents=True)
    (workspace / "tests/workflow").mkdir(parents=True)
    (workspace / "src/flowstate/training/experiment.py").write_text(
        "def train():\n    pass\n", encoding="utf-8",
    )
    (workspace / "tests/workflow/test_experiment.py").write_text(
        "class _FakeLoader:\n    pass\n", encoding="utf-8",
    )
    contract = _minimal_contract(["src/flowstate/training/experiment.py", "tests/workflow/test_experiment.py"])

    services = SimpleNamespace(workspace=SimpleNamespace(
        file_at_head=lambda _ws, _rel: "",
        revert=lambda _ws: pytest.fail("a test-only helper must not revert the patch"),
    ))
    workflow = AutonomousResearchWorkflow(services)

    workflow._verify_new_symbols_wired(workspace, contract)  # must not raise


@pytest.mark.asyncio
async def test_code_agent_patch_call_has_one_ten_minute_deadline(monkeypatch) -> None:
    observed: dict[str, Any] = {}

    def propose_patch(_contract, context):
        observed["context"] = context

        async def hang():
            await asyncio.sleep(3600)

        return hang()

    workflow = AutonomousResearchWorkflow(
        SimpleNamespace(agents=SimpleNamespace(propose_patch=propose_patch))
    )

    async def fake_wait_for(coro, timeout):
        observed["timeout"] = timeout
        coro.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr("flowstate.orchestration.graph.asyncio.wait_for", fake_wait_for)

    deadline = time.monotonic() + workflow.CODE_STAGE_TIMEOUT_SECONDS
    with pytest.raises(TimeoutError, match="600-second code-writing limit"):
        await workflow._propose_patch_before_deadline(object(), {}, deadline)

    assert 599.0 <= observed["timeout"] <= 600.0
    context = observed["context"]
    assert isinstance(context, dict)
    assert 599 <= context["code_writing_seconds_remaining"] <= 600


@pytest.mark.asyncio
async def test_code_node_labels_stage_deadline_for_contract_abandonment(tmp_path: Path, monkeypatch) -> None:
    from flowstate.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches

    contract = ExperimentContract(experiment_id="E-timeout", parent_run_id="B0", hypothesis="Pairwise ranking loss",
    observed_evidence_ids=[], primary_change="swap to pairwise loss", allowed_files=["src/flowstate/training/experiment.py", "configs/experiments/candidate.yaml"], prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
    falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
    comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
    budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
    fallback_run_id="B0", recovery_attempt_limit=2,)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.py").write_text("VALUE = 1\n", encoding="utf-8")

    async def reference_code_for_experiment(*_args, **_kwargs):
        return "", []

    workflow = AutonomousResearchWorkflow(SimpleNamespace(
        workspace=SimpleNamespace(create=lambda *_args, **_kwargs: (workspace, "parent")),
        knowledge=SimpleNamespace(retrieval=SimpleNamespace(
            reference_code_for_experiment=reference_code_for_experiment
        )),
        bedrock_output_limit=10_000,
        recovery=RecoveryController(),
    ))

    async def control_gate(_state):
        return None

    async def timed_out(_contract, _context, _deadline):
        raise TimeoutError("Code Agent exceeded the 600-second code-writing limit")

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(workflow, "_propose_patch_before_deadline", timed_out)
    monkeypatch.setattr(workflow, "_event", lambda *_args, **_kwargs: None)

    result = await workflow.code({
        "session_id": "s", "run_id": "run-timeout",
        "experiment_contract": contract.model_dump(mode="json"),
        "agent_output_tokens": 0, "recovery_attempt": 0,
    })

    assert result["failure_stage"] == "code"
    assert result["error_category"] == "code_stage_timeout"
    assert "600-second code-writing limit" in result["error"]


@pytest.mark.asyncio
async def test_inert_patch_retries_code_with_the_diagnosis_instead_of_new_research(tmp_path: Path, monkeypatch) -> None:
    # Reproduced in session-20260830T062240630878Z-599bf0db: the live inert
    # message said "ranking behavior", while the classifier only recognized
    # the obsolete phrase "training behavior". Eight code failures were
    # misclassified as infrastructure and each burned a fresh research plan.
    from flowstate.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches

    contract = ExperimentContract(experiment_id="E1", parent_run_id="B0", hypothesis="Pairwise BPR ranking loss for long_view",
    observed_evidence_ids=[], primary_change="swap to BPR", allowed_files=["src/flowstate/training/experiment.py", "configs/experiments/candidate.yaml"], prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
    falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
    comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
    budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
    fallback_run_id="B0", recovery_attempt_limit=2,)
    inert_error = (
        "patch produced no measurable change in ranking behavior: proxy-scale "
        "within-user validation ordering is identical to the unpatched experiment baseline"
    )
    recovery_events: list[dict] = []
    services = SimpleNamespace(
        recovery=RecoveryController(), maximum_experiments=10,
        frontier=SimpleNamespace(),
        ledger=SimpleNamespace(store_recovery_receipt=lambda *_args: None),
    )
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(
        workflow, "_event",
        lambda _state, _component, _stage, _event_type, _status, _summary, payload=None: recovery_events.append(payload or {}),
    )
    state = {
        "session_id": "s", "run_id": "run-1", "error": inert_error,
        "error_category": "behavior_unchanged", "failure_stage": "execute",
        "experiment_contract": contract.model_dump(mode="json"),
        "experiment_count": 0, "experiment_attempt_count": 1, "recovery_attempt": 0,
        "frontier": {"validation_best": "B0", "stable_fallback": "B0", "accepted_parent": "B0", "locked": False},
    }

    result = await workflow.recover(state)

    assert result["retry_target"] == "code"
    assert workflow._route_recovery({**state, **result}) == "code"
    assert result["last_execution_error"] == inert_error
    assert result["recovery_action"] == "activate_new_capability_in_config_or_callsites"
    assert state["experiment_count"] == 0
    assert state["experiment_attempt_count"] == 1
    assert recovery_events[-1]["retry_target"] == "code"
    assert recovery_events[-1]["experiment_id"] == "E1"


@pytest.mark.asyncio
async def test_code_agent_timeout_abandons_contract_and_returns_to_research(monkeypatch) -> None:
    from flowstate.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches

    contract = ExperimentContract(experiment_id="E-timeout", parent_run_id="B0", hypothesis="Pairwise ranking loss",
    observed_evidence_ids=[], primary_change="swap to pairwise loss", allowed_files=["src/flowstate/training/experiment.py", "configs/experiments/candidate.yaml"], prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
    falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
    comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
    budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
    fallback_run_id="B0", recovery_attempt_limit=2,)
    recovery_events: list[dict] = []
    workflow = AutonomousResearchWorkflow(SimpleNamespace(
        recovery=RecoveryController(), maximum_experiments=10,
        ledger=SimpleNamespace(store_recovery_receipt=lambda *_args: None),
    ))

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(
        workflow, "_event",
        lambda _state, _component, _stage, _event_type, _status, _summary, payload=None: recovery_events.append(payload or {}),
    )
    state = {
        "session_id": "s", "run_id": "run-timeout",
        "error": "TimeoutError: Code Agent exceeded the 600-second code-writing limit",
        "error_category": "code_stage_timeout", "failure_stage": "code",
        "experiment_contract": contract.model_dump(mode="json"),
        "experiment_count": 0, "experiment_attempt_count": 1, "recovery_attempt": 0,
        "frontier": {"validation_best": "B0", "stable_fallback": "B0", "accepted_parent": "B0", "locked": False},
    }

    result = await workflow.recover(state)

    assert result["retry_target"] == "research"
    assert result["last_execution_error"] == ""
    assert result["recovery_action"] == "abandon_timed_out_contract"
    assert workflow._route_recovery({**state, **result}) == "research"
    assert recovery_events[-1]["retry_target"] == "research"


@pytest.mark.asyncio
async def test_repeated_invalid_research_contracts_stop_instead_of_looping(monkeypatch) -> None:
    stored_frontiers: list[FrontierState] = []
    events: list[tuple[str, str]] = []
    services = SimpleNamespace(
        recovery=RecoveryController(),
        research_strategy={"maximum_consecutive_research_failures": 2},
        maximum_experiments=10,
        bedrock_input_limit=10_000,
        bedrock_output_limit=10_000,
        total_wall_seconds=0,
        total_gpu_hours=0.0,
        ledger=SimpleNamespace(
            store_recovery_receipt=lambda *_args: None,
            store_frontier=lambda _session, frontier: stored_frontiers.append(frontier),
        ),
    )
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(
        workflow,
        "_event",
        lambda _state, component, _stage, _event_type, _status, summary, _payload=None: events.append(
            (component, summary)
        ),
    )
    state = {
        "session_id": "s",
        "run_id": "research-invalid-2",
        "error": "ensemble is unavailable until two distinct models qualify",
        "error_category": "experiment_scope",
        "failure_stage": "research",
        "consecutive_research_failures": 2,
        "experiment_count": 1,
        "experiment_attempt_count": 4,
        "recovery_attempt": 0,
        "frontier": {
            "validation_best": "E2",
            "stable_fallback": "B0",
            "accepted_parent": "E2",
            "locked": False,
        },
    }

    result = await workflow.recover(state)

    assert result["stop"] is True
    assert result["stop_reason"] == "research_failure_limit"
    assert workflow._route_recovery({**state, **result}) == "stop"
    assert "research-invalid-2" in stored_frontiers[-1].failed
    assert any(component == "watchdog" and "repeated invalid" in summary for component, summary in events)


@pytest.mark.asyncio
async def test_exhausted_code_retries_fall_back_to_fresh_research(tmp_path: Path, monkeypatch) -> None:
    from flowstate.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches

    contract = ExperimentContract(experiment_id="E1", parent_run_id="B0", hypothesis="Pairwise BPR ranking loss for long_view",
    observed_evidence_ids=[], primary_change="swap to BPR", allowed_files=["src/flowstate/training/experiment.py", "configs/experiments/candidate.yaml"], prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
    falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
    comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
    budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
    fallback_run_id="B0", recovery_attempt_limit=1,)
    services = SimpleNamespace(
        recovery=RecoveryController(), maximum_experiments=10, frontier=SimpleNamespace(),
        bedrock_input_limit=10_000, bedrock_output_limit=10_000, total_wall_seconds=0, total_gpu_hours=0.0,
        ledger=SimpleNamespace(store_recovery_receipt=lambda *_args: None),
    )
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None
    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(workflow, "_event", lambda *_args, **_kwargs: None)

    state = {
        "session_id": "s", "run_id": "run-1",
        "error": "patch produced no measurable change in ranking behavior",
        "error_category": "behavior_unchanged", "failure_stage": "execute",
        "experiment_contract": contract.model_dump(mode="json"),
        "experiment_count": 0, "experiment_attempt_count": 1,
        "recovery_attempt": 1,  # already used the single permitted attempt
        "frontier": {"validation_best": "B0", "stable_fallback": "B0", "accepted_parent": "B0", "locked": False},
    }

    result = await workflow.recover(state)

    assert result["retry_target"] == "research"
    assert workflow._route_recovery({**state, **result}) == "research"
    assert "run-1" in result["frontier"]["failed"]


@pytest.mark.asyncio
async def test_research_stops_at_completed_experiment_budget(monkeypatch) -> None:
    # maximum_experiments counts runs that reached official validation. Code
    # and proxy failures use bounded recovery/resource budgets instead.
    locked = {}
    services = SimpleNamespace(
        maximum_experiments=1, bedrock_input_limit=10_000, bedrock_output_limit=10_000,
        total_wall_seconds=0, total_gpu_hours=0.0,
        frontier=SimpleNamespace(budget_stop=lambda state: state.model_copy(update={"locked": True})),
        ledger=SimpleNamespace(store_frontier=lambda _session, frontier: locked.update(value=frontier.locked)),
        knowledge=SimpleNamespace(),
        agents=SimpleNamespace(),
    )

    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(workflow, "_event", lambda *args, **kwargs: None)

    state = {
        "session_id": "s", "run_id": "run-1", "experiment_count": 1,
        "frontier": {"validation_best": "B0", "stable_fallback": "B0", "accepted_parent": "B0", "locked": False},
    }

    result = await workflow.research(state)

    assert result["stop"] is True
    assert result["stop_reason"] == "budget"
    assert result["frontier"]["locked"] is True
    assert locked == {"value": True}
    assert workflow._route_research({**state, **result}) == "stop"




@pytest.mark.asyncio
async def test_code_agent_infeasible_contract_returns_to_research(monkeypatch) -> None:
    contract = _minimal_contract(["a.py"])
    workflow = AutonomousResearchWorkflow(
        SimpleNamespace(
            recovery=RecoveryController(),
            maximum_experiments=10,
            ledger=SimpleNamespace(store_recovery_receipt=lambda *_args: None),
        )
    )

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(workflow, "_event", lambda *_args, **_kwargs: None)
    state = {
        "session_id": "s",
        "run_id": "run-scope",
        "error": "ExperimentScopeError: full transformer pipeline cannot fit",
        "error_category": "experiment_scope",
        "failure_stage": "code",
        "experiment_contract": contract.model_dump(mode="json"),
        "experiment_count": 0,
        "experiment_attempt_count": 1,
        "recovery_attempt": 0,
        "frontier": {
            "validation_best": "B0",
            "stable_fallback": "B0",
            "accepted_parent": "B0",
            "locked": False,
        },
    }

    result = await workflow.recover(state)

    assert result["retry_target"] == "research"
    assert result["recovery_action"] == "abandon_oversized_contract"


def test_route_recovery_retries_unless_explicitly_stopped() -> None:
    workflow = AutonomousResearchWorkflow(SimpleNamespace())
    assert workflow._route_recovery({"stop": False}) == "research"
    assert workflow._route_recovery({"stop": True}) == "stop"


def test_research_history_exposes_code_timeout_as_scope_evidence(tmp_path: Path) -> None:
    ledger = WorkflowLedger(tmp_path / "flowstate.sqlite3")
    session_id = ledger.create_session()
    contract = {
        "experiment_id": "E-sasrec",
        "hypothesis": "Build a full SASRec history pipeline",
        "primary_change": "Add SASRec transformer",
    }
    ledger.append_event(
        session_id=session_id,
        run_id="run-sasrec",
        component_id="scientist",
        execution_id="research-1",
        stage="research",
        event_type="plan",
        status=ComponentStatus.SUCCEEDED,
        plain_summary="One bounded experiment selected",
        payload={"contract": contract},
    )
    ledger.append_event(
        session_id=session_id,
        run_id="run-sasrec",
        component_id="coder",
        execution_id="code-1",
        stage="patch",
        event_type="failed",
        status=ComponentStatus.FAILED,
        plain_summary="Code Agent exceeded the 600-second code-writing limit",
        payload={"error": "TimeoutError"},
    )
    ledger.append_event(
        session_id=session_id,
        run_id="run-sasrec",
        component_id="recovery",
        execution_id="recovery-1",
        stage="recovery",
        event_type="recovery",
        status=ComponentStatus.READY,
        plain_summary="abandon_timed_out_contract",
        payload={
            "category": "code_stage_timeout",
            "retry_target": "research",
        },
    )
    workflow = AutonomousResearchWorkflow(SimpleNamespace(ledger=ledger))

    summaries = workflow._prior_run_summaries(session_id, [contract])

    assert summaries == [
        {
            **contract,
            "run_id": "run-sasrec",
            "outcome": "abandoned_after_code_timeout",
            "failure_stage": "code",
            "failure_category": "code_stage_timeout",
            "failure_summary": "Code Agent exceeded the 600-second code-writing limit",
            "recovery_action": "abandon_timed_out_contract",
            "retry_target": "research",
        }
    ]


@pytest.mark.asyncio
async def test_research_resets_recovery_attempt_and_forwards_real_run_history(tmp_path: Path, monkeypatch) -> None:
    # recovery_attempt previously never reset between unrelated failures (a
    # code-patch failure, then a separate hallucinated-citation failure),
    # exhausting the per-experiment cap after two heterogeneous incidents in
    # the whole session instead of two retries of the same issue. Also,
    # context["runs"] was always hardcoded empty, so the Research Agent had
    # no memory of already-attempted hypotheses and repeated itself.
    profile_path = tmp_path / "profile.json"
    profile_path.write_text("{}", encoding="utf-8")

    class FakeCard:
        supporting: list = []
        contradicting: list = []
        source_ids: list = []
        meta = SimpleNamespace(source_mode="cache")
        missing_evidence: list = []

    class FakeRetrieval:
        async def research_card(self, *_args, **_kwargs):
            return FakeCard()

    seen_contexts = []
    fail_next = {"value": True}

    class FakeAgents:
        async def research(self, context):
            seen_contexts.append(context)
            if fail_next["value"]:
                raise ValueError("Research Agent cited evidence not supplied by MCP")
            from flowstate.agents.azure_foundry import AgentUsage
            from flowstate.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches
            contract = ExperimentContract(experiment_id="E2", parent_run_id="B0", hypothesis="A genuinely new mechanism, not repeated",
            observed_evidence_ids=[], primary_change="try something new", mechanism_id="new_mechanism",
            decision_rationale="Prior BPR evidence motivates a different bounded mechanism.",
            allowed_files=["src/flowstate/training/experiment.py", "configs/experiments/candidate.yaml"], prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
            falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
            comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
            budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
            fallback_run_id="B0", recovery_attempt_limit=1,)
            return SimpleNamespace(value=contract, usage=AgentUsage(input_tokens=10, output_tokens=10, model_id="fake"))


    prior_contract = {"experiment_id": "E1", "hypothesis": "BPR pairwise loss", "primary_change": "swap loss to BPR"}

    services = SimpleNamespace(
        knowledge=SimpleNamespace(retrieval=FakeRetrieval()),
        agents=FakeAgents(),
        recovery=RecoveryController(),
        contract=SimpleNamespace(public_summary=lambda: {}),
        maximum_experiments=10, bedrock_input_limit=100_000, bedrock_output_limit=100_000,
        total_wall_seconds=0, total_gpu_hours=0.0,
        ledger=SimpleNamespace(list_contracts=lambda _sid: [prior_contract], store_contract=lambda *_a, **_k: None),
    )
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(workflow, "_event", lambda *args, **kwargs: None)

    base_state = {
        "session_id": "session-1",
        "profile_receipt": {"profile": {"path": str(profile_path)}},
        "frontier": {"validation_best": "B0", "stable_fallback": "B0", "accepted_parent": "B0", "locked": False},
        "baseline_metric": {"primary": 0.60},
        "experiment_count": 3, "agent_input_tokens": 0, "agent_output_tokens": 0,
        "recovery_attempt": 2,  # simulates an unrelated earlier failure's leftover count
        "consecutive_research_failures": 2,
        "last_research_error": "an unrelated earlier Research Agent error",
    }

    failure_result = await workflow.research(base_state)
    assert failure_result["recovery_attempt"] == 0
    assert failure_result["consecutive_research_failures"] == 1
    assert failure_result["error"]
    assert seen_contexts[-1]["runs"][0] == {
        **prior_contract,
        "run_id": None,
        "outcome": "unknown",
        "failure_stage": None,
        "failure_category": None,
        "failure_summary": None,
        "recovery_action": None,
        "retry_target": None,
    }
    assert seen_contexts[-1]["execution_constraints"]["code_writing_wall_seconds"] == 600
    assert seen_contexts[-1]["execution_constraints"]["fast_proxy_wall_seconds"] == 600

    fail_next["value"] = False
    success_result = await workflow.research({**base_state, "recovery_attempt": 2})
    assert success_result["recovery_attempt"] == 0
    assert success_result["consecutive_research_failures"] == 0
    assert success_result["error"] == ""


@pytest.mark.asyncio
async def test_research_query_rotates_priority_area_by_attempt_count(tmp_path: Path, monkeypatch) -> None:
    # Reproduced live: the query passed to research_card() was a single
    # hardcoded literal string forever, so 69 contracts across 22 sessions
    # cited only 5 distinct paper_ids total out of 20 curated papers spanning
    # 7 priority areas. The query and its priority_area filter must now vary
    # with every bounded research attempt, including failed Research Agent
    # calls that never produced a contract. No trust_tier filter -- curated
    # and discovered (Hugging Face) papers are both ranked and handed to the
    # agent -- but every call requires verified code
    # (EvidenceFilters(require_code=True)) and bypasses the 7-day query cache.
    profile_path = tmp_path / "profile.json"
    profile_path.write_text("{}", encoding="utf-8")

    class FakeCard:
        supporting: list = []
        contradicting: list = []
        source_ids: list = []
        meta = SimpleNamespace(source_mode="cache")
        missing_evidence: list = []

    seen_calls = []

    class FakeRetrieval:
        async def research_card(self, hypothesis, max_evidence, **kwargs):
            seen_calls.append({"hypothesis": hypothesis, "filters": kwargs.get("filters"), "bypass_cache": kwargs.get("bypass_cache")})
            return FakeCard()

    from flowstate.agents.azure_foundry import AgentUsage
    from flowstate.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches

    class FakeAgents:
        async def research(self, _context):
            contract = ExperimentContract(experiment_id="E", parent_run_id="B0", hypothesis="Some sufficiently long hypothesis text",
            observed_evidence_ids=[], primary_change="try something", mechanism_id=f"rotation_{len(seen_calls)}",
            decision_rationale="The next priority area follows the observed experiment rotation.",
            allowed_files=["src/flowstate/training/experiment.py", "configs/experiments/candidate.yaml"], prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
            falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
            comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
            budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
            fallback_run_id="B0", recovery_attempt_limit=1,)
            return SimpleNamespace(value=contract, usage=AgentUsage(input_tokens=10, output_tokens=10, model_id="fake"))

    prior_count = {"value": 0}
    services = SimpleNamespace(
        knowledge=SimpleNamespace(retrieval=FakeRetrieval()),
        agents=FakeAgents(),
        contract=SimpleNamespace(public_summary=lambda: {}),
        maximum_experiments=10, bedrock_input_limit=100_000, bedrock_output_limit=100_000,
        total_wall_seconds=0, total_gpu_hours=0.0,
        ledger=SimpleNamespace(
            list_contracts=lambda _sid: [{"experiment_id": f"E{i}"} for i in range(prior_count["value"])],
            store_contract=lambda *_a, **_k: None,
        ),
    )
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(workflow, "_event", lambda *args, **kwargs: None)

    state = {
        "session_id": "session-1",
        "profile_receipt": {"profile": {"path": str(profile_path)}},
        "frontier": {"validation_best": "B0", "stable_fallback": "B0", "accepted_parent": "B0", "locked": False},
        "baseline_metric": {"primary": 0.60},
        "experiment_count": 0, "agent_input_tokens": 0, "agent_output_tokens": 0, "recovery_attempt": 0,
    }

    rotation = workflow._PRIORITY_AREA_ROTATION
    queries = workflow._PRIORITY_AREA_QUERIES
    for i in range(len(rotation) + 1):  # one full cycle plus one, to prove it wraps
        prior_count["value"] = i
        state["experiment_attempt_count"] = i
        await workflow.research(state)
        expected_area = rotation[i % len(rotation)]
        assert seen_calls[-1]["hypothesis"] == queries[expected_area]
        assert seen_calls[-1]["filters"] == EvidenceFilters(require_code=True)
        assert seen_calls[-1]["bypass_cache"] is True

    # Every call in the cycle must have used a distinct query.
    assert len({call["hypothesis"] for call in seen_calls[:len(rotation)]}) == len(rotation)
    # The (len(rotation)+1)th call must repeat the first area, proving the wrap.
    assert seen_calls[len(rotation)]["hypothesis"] == seen_calls[0]["hypothesis"]


@pytest.mark.asyncio
async def test_research_auto_corrects_content_hash_citation_confusion(tmp_path: Path, monkeypatch) -> None:
    # Reproduced live against Azure: the model periodically cites a paper's
    # content_hash instead of its paper_id when both are sent as sibling
    # hash-like fields on the same evidence item (~40% of live calls). Fixed
    # by (a) no longer sending content_hash to the model at all, and (b)
    # auto-correcting a content_hash citation back to its real paper_id
    # instead of burning a full recovery retry on an unambiguous mix-up.
    profile_path = tmp_path / "profile.json"
    profile_path.write_text("{}", encoding="utf-8")

    paper = SimpleNamespace(paper_id="arxiv:1205.2618", title="BPR", relevance_notes="pairwise ranking", content_hash="deadbeef" * 8)
    match = SimpleNamespace(paper=paper, model_dump=lambda mode: {"paper_id": paper.paper_id})

    class FakeCard:
        supporting = [match]
        contradicting: list = []
        source_ids = [paper.paper_id]
        meta = SimpleNamespace(source_mode="cache")
        missing_evidence: list = []

    class FakeRetrieval:
        async def research_card(self, *_args, **_kwargs):
            return FakeCard()

    seen_contexts = []

    class FakeAgents:
        async def research(self, context):
            seen_contexts.append(context)
            from flowstate.agents.azure_foundry import AgentUsage
            from flowstate.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches
            contract = ExperimentContract(experiment_id="E2", parent_run_id="B0", hypothesis="Pairwise BPR ranking loss for long_view",
            observed_evidence_ids=[paper.content_hash], primary_change="swap to BPR", mechanism_id="bpr_citation",
            decision_rationale="The cited ranking evidence supports this bounded loss change.",
            allowed_files=["src/flowstate/training/experiment.py", "configs/experiments/candidate.yaml"], prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
            falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
            comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
            budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
            fallback_run_id="B0", recovery_attempt_limit=1,)
            return SimpleNamespace(value=contract, usage=AgentUsage(input_tokens=10, output_tokens=10, model_id="fake"))

    services = SimpleNamespace(
        knowledge=SimpleNamespace(retrieval=FakeRetrieval()),
        agents=FakeAgents(),
        contract=SimpleNamespace(public_summary=lambda: {}),
        maximum_experiments=10, bedrock_input_limit=100_000, bedrock_output_limit=100_000,
        total_wall_seconds=0, total_gpu_hours=0.0,
        ledger=SimpleNamespace(list_contracts=lambda _sid: [], store_contract=lambda *_a, **_k: None),
    )
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(workflow, "_event", lambda *args, **kwargs: None)

    state = {
        "session_id": "session-1",
        "profile_receipt": {"profile": {"path": str(profile_path)}},
        "frontier": {"validation_best": "B0", "stable_fallback": "B0", "accepted_parent": "B0", "locked": False},
        "baseline_metric": {"primary": 0.60},
        "experiment_count": 0, "experiment_attempt_count": 0,
        "agent_input_tokens": 0, "agent_output_tokens": 0, "recovery_attempt": 0,
    }

    result = await workflow.research(state)

    assert result["error"] == ""
    assert result["experiment_contract"]["observed_evidence_ids"] == [paper.paper_id]
    assert "content_hash" not in seen_contexts[-1]["evidence"][0]
    assert result["experiment_attempt_count"] == 1
    assert "experiment_count" not in result


@pytest.mark.asyncio
async def test_research_still_rejects_a_truly_unknown_citation(tmp_path: Path, monkeypatch) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text("{}", encoding="utf-8")

    paper = SimpleNamespace(paper_id="arxiv:1205.2618", title="BPR", relevance_notes="pairwise ranking", content_hash="deadbeef" * 8)
    match = SimpleNamespace(paper=paper, model_dump=lambda mode: {"paper_id": paper.paper_id})

    class FakeCard:
        supporting = [match]
        contradicting: list = []
        source_ids = [paper.paper_id]
        meta = SimpleNamespace(source_mode="cache")
        missing_evidence: list = []

    class FakeRetrieval:
        async def research_card(self, *_args, **_kwargs):
            return FakeCard()

    class FakeAgents:
        async def research(self, context):
            from flowstate.agents.azure_foundry import AgentUsage
            from flowstate.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches
            contract = ExperimentContract(experiment_id="E2", parent_run_id="B0", hypothesis="Pairwise BPR ranking loss for long_view",
            observed_evidence_ids=["fabricated-paper-id"], primary_change="swap to BPR", mechanism_id="invalid_citation",
            decision_rationale="The supplied evidence was selected for this bounded loss change.",
            allowed_files=["src/flowstate/training/experiment.py", "configs/experiments/candidate.yaml"], prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
            falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
            comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
            budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
            fallback_run_id="B0", recovery_attempt_limit=1,)
            return SimpleNamespace(value=contract, usage=AgentUsage(input_tokens=10, output_tokens=10, model_id="fake"))

    services = SimpleNamespace(
        knowledge=SimpleNamespace(retrieval=FakeRetrieval()),
        agents=FakeAgents(),
        recovery=RecoveryController(),
        contract=SimpleNamespace(public_summary=lambda: {}),
        maximum_experiments=10, bedrock_input_limit=100_000, bedrock_output_limit=100_000,
        total_wall_seconds=0, total_gpu_hours=0.0,
        ledger=SimpleNamespace(list_contracts=lambda _sid: [], store_contract=lambda *_a, **_k: None),
    )
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(workflow, "_event", lambda *args, **kwargs: None)

    state = {
        "session_id": "session-1",
        "profile_receipt": {"profile": {"path": str(profile_path)}},
        "frontier": {"validation_best": "B0", "stable_fallback": "B0", "accepted_parent": "B0", "locked": False},
        "baseline_metric": {"primary": 0.60},
        "experiment_count": 0, "agent_input_tokens": 0, "agent_output_tokens": 0, "recovery_attempt": 0,
    }

    result = await workflow.research(state)

    assert "fabricated-paper-id" in result["error"]
    assert paper.paper_id in result["error"]


@pytest.mark.asyncio
async def test_baseline_runs_label_shuffle_control_and_halts_when_suspicious(tmp_path: Path, monkeypatch) -> None:
    # Plan_Workflow §5.3 requires the label-shuffle negative control inside the
    # run. It previously only existed in the `reproduce-baseline` CLI, so the
    # "Check Data Safety" component never executed during `run`.
    from flowstate.contract.models import MetricReceipt

    receipt = MetricReceipt(
        receipt_id="m", run_id="harness", prediction_artifact_id="memory", evaluator_hash="h",
        config_hash="c", gauc=0.5, ndcg_at_5=0.45, primary=0.475, users=2, rows=4,
        comparable=False, scope="validation", receipt_hash="rh",
    )
    events: list[tuple[str, str]] = []
    services = SimpleNamespace(
        baseline=SimpleNamespace(
            reproduce=lambda _dir: {"status": "succeeded", "seeds": [{"metrics": {
                "run_id": "B0-seed-0", "primary": 0.6, "gauc": 0.66, "ndcg_at_5": 0.53,
                "evaluator_hash": "eval-hash", "config_hash": "cfg-hash",
                "prediction_artifact_id": "pred", "users": 100, "rows": 200,
            }}]},
            harness_checks=lambda _dir: {"random": receipt},
            label_shuffle_control=lambda _dir: {"passed": False, "bound": 0.4953, "receipt": receipt.model_dump(mode="json")},
        ),
        frontier=SimpleNamespace(),
        ledger=SimpleNamespace(store_metric_receipt=lambda *_a: None, store_frontier=lambda *_a: None),
    )
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(
        workflow, "_event",
        lambda _state, component, _stage, event_type, *_args, **_kwargs: events.append((component, event_type)),
    )

    result = await workflow.baseline({"session_id": "s", "transform_dir": str(tmp_path)})

    assert ("phase_guard", "integrity_halt") in events
    assert result["stop"] is True
    assert result["stop_reason"] == "baseline_gate"
    assert "sanity" in result["error"]



@pytest.mark.asyncio
async def test_baseline_training_keeps_event_loop_responsive(tmp_path: Path, monkeypatch) -> None:
    def reproduce(_transform_dir):
        time.sleep(0.2)
        return {"status": "succeeded", "seeds": [{"metrics": {
            "run_id": "B0-seed-0", "primary": 0.6, "gauc": 0.66, "ndcg_at_5": 0.53,
            "evaluator_hash": "eval-hash", "config_hash": "cfg-hash",
            "prediction_artifact_id": "pred", "users": 100, "rows": 200,
        }}]}

    services = SimpleNamespace(
        baseline=SimpleNamespace(
            reproduce=reproduce,
            harness_checks=lambda _dir: {},
            label_shuffle_control=lambda _dir: {"passed": True, "bound": 0.4953},
        ),
        frontier=SimpleNamespace(
            register_baseline=lambda _run_id: SimpleNamespace(
                model_dump=lambda mode: {"validation_best": "B0"}
            )
        ),
        ledger=SimpleNamespace(
            store_metric_receipt=lambda *_args: None,
            store_frontier=lambda *_args: None,
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


@pytest.mark.asyncio
async def test_baseline_evidence_is_persisted_before_sanity_check_failure(tmp_path: Path, monkeypatch) -> None:
    baseline_result = {
        "status": "succeeded",
        "seeds": [{"metrics": {
            "run_id": "B0-seed-0", "primary": 0.6016, "gauc": 0.6674, "ndcg_at_5": 0.5357,
            "evaluator_hash": "eval-hash", "config_hash": "cfg-hash",
            "prediction_artifact_id": "pred", "users": 100, "rows": 200,
        }}],
    }
    stored_metrics: list[str] = []
    events: list[tuple[str, str, ComponentStatus, dict]] = []

    def fail_harness(_transform):
        raise UnicodeDecodeError("charmap", b"\x90", 0, 1, "character maps to <undefined>")

    services = SimpleNamespace(
        baseline=SimpleNamespace(reproduce=lambda _dir: baseline_result, harness_checks=fail_harness),
        ledger=SimpleNamespace(
            store_metric_receipt=lambda _session, run_id, _metric: stored_metrics.append(run_id),
        ),
    )
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(
        workflow,
        "_event",
        lambda _state, component, _stage, event_type, status, _summary, payload=None:
            events.append((component, event_type, status, payload or {})),
    )

    result = await workflow.baseline({"session_id": "s", "transform_dir": str(tmp_path)})

    assert stored_metrics == ["B0-seed-0"]
    assert ("trainer", "completed", ComponentStatus.SUCCEEDED) in [
        (component, event_type, status) for component, event_type, status, _payload in events
    ]
    assert ("phase_guard", "sanity_checks", ComponentStatus.RUNNING) in [
        (component, event_type, status) for component, event_type, status, _payload in events
    ]
    failure = events[-1]
    assert failure[:3] == ("phase_guard", "failed", ComponentStatus.FAILED)
    assert failure[3]["baseline_result"] == baseline_result
    assert result["baseline_result"] == baseline_result
    assert result["stop_reason"] == "baseline_failure"


@pytest.mark.asyncio
async def test_baseline_comparator_averages_all_five_seeds_not_seed_zero(tmp_path: Path, monkeypatch) -> None:
    # decide() builds its real MetricReceipt comparator straight from
    # state["best_metric"]/"parent_metric"; these were set from
    # result["seeds"][0] alone, so every experiment in every session was
    # silently compared against one arbitrary noisy seed while the UI's
    # "Official FM Baseline (5 seeds)" table showed the honest mean of all
    # five -- two different numbers, only one of which actually drove
    # decisions. Reproduced with the session's real seed values.
    from flowstate.contract.models import MetricReceipt

    seed_values = [
        (0.6671326321610643, 0.5358048805448538, 0.601468756352959),
        (0.6673954513271534, 0.5361264979255713, 0.6017609746263624),
        (0.6670635117150168, 0.5351164495629801, 0.6010899806389984),
        (0.6674614320871909, 0.5355452797368637, 0.6015033559120273),
        (0.6679479198936048, 0.536126483327846, 0.6020372016107254),
    ]
    seeds = [
        {"metrics": {
            "run_id": f"B0-seed-{i}", "gauc": gauc, "ndcg_at_5": ndcg, "primary": primary,
            "evaluator_hash": "eval-hash", "config_hash": "cfg-hash",
            "prediction_artifact_id": "pred", "users": 100, "rows": 200,
        }}
        for i, (gauc, ndcg, primary) in enumerate(seed_values)
    ]
    services = SimpleNamespace(
        baseline=SimpleNamespace(
            reproduce=lambda _dir: {"status": "succeeded", "seeds": seeds},
            harness_checks=lambda _dir: {},
            label_shuffle_control=lambda _dir: {"passed": True, "bound": 0.4953},
        ),
        frontier=SimpleNamespace(
            register_baseline=lambda _run_id: SimpleNamespace(model_dump=lambda mode: {"validation_best": "B0"})
        ),
        ledger=SimpleNamespace(store_metric_receipt=lambda *_a: None, store_frontier=lambda *_a: None),
    )
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(workflow, "_event", lambda *args, **kwargs: None)

    result = await workflow.baseline({"session_id": "s", "transform_dir": str(tmp_path)})

    for key in ("baseline_metric", "best_metric", "parent_metric"):
        metric = result[key]
        assert metric["primary"] == pytest.approx(0.6015720538282145, abs=1e-9)
        assert metric["gauc"] == pytest.approx(0.667400189436806, abs=1e-9)
        assert metric["ndcg_at_5"] == pytest.approx(0.535743918219623, abs=1e-9)
        # Must not equal seed-0's value alone -- the bug this reproduces.
        assert metric["primary"] != seed_values[0][2]
        assert metric["run_id"] == "B0"
        # Must still validate as a real MetricReceipt (decide() does exactly this).
        MetricReceipt.model_validate(metric)


@pytest.mark.asyncio
async def test_1k_decision_uses_observed_b0_when_no_published_baseline(
    monkeypatch,
) -> None:
    def metric(run_id: str, primary: float) -> dict[str, Any]:
        return MetricReceipt(
            receipt_id=f"metric-{run_id}",
            run_id=run_id,
            prediction_artifact_id=f"prediction-{run_id}",
            evaluator_hash="e" * 64,
            config_hash="c" * 64,
            gauc=primary,
            ndcg_at_5=primary,
            primary=primary,
            users=978,
            rows=2_524_980,
            comparable=True,
            scope="validation",
            receipt_hash="r" * 64,
        ).model_dump(mode="json")

    frontier = FrontierState(
        validation_best="B0",
        stable_fallback="B0",
        accepted_parent="B0",
    )
    events: list[dict[str, Any]] = []
    services = SimpleNamespace(
        contract=SimpleNamespace(baseline_valid={}),
        research_strategy={},
        frontier=SimpleNamespace(
            decide=lambda current, _receipt, run_id, _best, _parent, **_kwargs: (
                current.model_copy(update={"rejected": [run_id]}),
                "reject",
                False,
            ),
            budget_stop=lambda current: current,
        ),
        ledger=SimpleNamespace(store_frontier=lambda *_args: None),
        maximum_experiments=10,
        bedrock_input_limit=10_000,
        bedrock_output_limit=10_000,
        total_gpu_hours=0.0,
        total_wall_seconds=0,
    )
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(
        workflow,
        "_event",
        lambda *_args, **_kwargs: events.append(
            _kwargs.get("payload")
            or (_args[-1] if _args and isinstance(_args[-1], dict) else {})
        ),
    )
    baseline = metric("B0", 0.6358024841378812)
    candidate = metric("E1", 0.6273305833984772)
    result = await workflow.decide(
        {
            "session_id": "session",
            "run_id": "E1",
            "frontier": frontier.model_dump(mode="json"),
            "baseline_metric": baseline,
            "best_metric": baseline,
            "parent_metric": baseline,
            "metric_receipt": candidate,
            "experiment_contract": _minimal_contract(
                ["src/flowstate/training/experiment.py"]
            ).model_dump(mode="json"),
            "experiment_count": 1,
        }
    )

    assert result["stop"] is False
    assert events[-1]["delta_vs_official_baseline"] == pytest.approx(
        0.6273305833984772 - 0.6358024841378812
    )



@pytest.mark.asyncio
async def test_baseline_terminal_failure_is_not_attributed_to_decision_agent(tmp_path: Path, monkeypatch) -> None:
    import flowstate.orchestration.graph as graph_module

    ledger = WorkflowLedger(tmp_path / "flowstate.sqlite3")
    session = ledger.create_session()

    class FakeSaver:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def setup(self):
            return None

    class FakeGraph:
        async def ainvoke(self, state, config):
            return {
                **state,
                "stop": True,
                "stop_reason": "baseline_failure",
                "error": "UnicodeDecodeError: invalid Windows locale decode",
            }

    services = SimpleNamespace(
        ledger=ledger,
        knowledge=SimpleNamespace(close=lambda: asyncio.sleep(0)),
    )
    workflow = AutonomousResearchWorkflow(services)
    monkeypatch.setattr(
        graph_module,
        "AsyncSqliteSaver",
        SimpleNamespace(from_conn_string=lambda _path: FakeSaver()),
    )
    monkeypatch.setattr(workflow, "_build", lambda checkpointer=None: FakeGraph())

    result = await workflow.run(session)

    assert result["stop_reason"] == "baseline_failure"
    snapshot = ledger.snapshot(session)
    assert snapshot.status == ComponentStatus.FAILED
    terminal = ledger.events(session)[-1]
    assert terminal.component_id == "orchestrator"
    assert terminal.stage == "workflow"
    assert terminal.status == ComponentStatus.FAILED
    assert "baseline execution" in terminal.plain_summary

def test_finalization_is_one_way(tmp_path: Path, monkeypatch) -> None:
    ledger = WorkflowLedger(tmp_path / "flowstate.sqlite3")
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
    tier4 = artifacts / "runs/session/run-1/attempt-0/E1/tier4"
    checkpoint = tier4 / "model/checkpoint.pt"
    checkpoint.parent.mkdir(parents=True)
    model = FactorizationMachine(20, 4)
    torch.save({"state_dict": model.state_dict(), "dimension": 20, "config": {"model": {"factors": 4}}}, checkpoint)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ledger.append_event(
        session_id=session, run_id="run-1", component_id="coder", execution_id="patch",
        stage="patch", event_type="completed", status=ComponentStatus.SUCCEEDED,
        plain_summary="patched", payload={"workspace": str(workspace)},
    )
    ledger.append_event(
        session_id=session, run_id="run-1", component_id="trainer", execution_id="tier4",
        stage="execute", event_type="tier4", status=ComponentStatus.SUCCEEDED,
        plain_summary="trained", payload={"receipt": {"output_directory": str(tier4)}},
    )
    finalizer = SubmissionFinalizer(load_challenge_contract(), ledger, artifacts)
    monkeypatch.setattr(finalizer, "_test_features", lambda _: ({
        "X": np.asarray([[1, 2, 3, 4, 5]], dtype=np.int32),
        "users": np.asarray(["u"]), "videos": np.asarray(["v"]),
    }, ["u"], ["v"]))
    monkeypatch.setattr(
        "flowstate.reporting.finalizer.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="✓ ok".encode("utf-8"), stderr=b""),
    )
    result = finalizer.package(session)
    assert result["test_prediction_passes"] == 1
    assert result["schema_check"]["stdout"] == "✓ ok"
    finalized = [
        event for event in ledger.events(session) if event.event_type == "finalized"
    ]
    assert [event.component_id for event in finalized] == ["finalizer", "submission"]
    assert finalized[0].payload["manifest"]["manifest_hash"] == result["manifest_hash"]
    assert ledger.snapshot(session).finalized
    assert result["event_chain_valid"]
    with pytest.raises(RuntimeError, match="already been finalized"):
        finalizer.package(session)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("duplicate_of_run_id", "expected_count"),
    [(None, 4), ("run-prior", None)],
)
async def test_completed_experiment_budget_increments_only_after_official_validation(
    tmp_path: Path,
    monkeypatch,
    duplicate_of_run_id: str | None,
    expected_count: int | None,
) -> None:
    from flowstate.contract.models import MetricReceipt

    transform = tmp_path / "transform"
    model = tmp_path / "tier4" / "model"
    transform.mkdir()
    model.mkdir(parents=True)
    np.save(model / "valid_scores.npy", np.asarray([0.2, 0.8], dtype=np.float32))
    np.savez_compressed(
        transform / "valid.npz",
        users=np.asarray(["u", "u"]),
        videos=np.asarray(["v1", "v2"]),
        y=np.asarray([0, 1], dtype=np.float32),
    )
    receipt = MetricReceipt(
        receipt_id="metric", run_id="run-1", prediction_artifact_id="pred",
        evaluator_hash="evaluator", config_hash="config", gauc=1.0,
        ndcg_at_5=1.0, primary=1.0, users=1, rows=2,
        comparable=True, scope="validation", receipt_hash="hash",
    )
    services = SimpleNamespace(
        evaluator=SimpleNamespace(
            write_predictions=lambda *_args: "prediction-hash",
            score=lambda **_kwargs: receipt,
        ),
        ledger=SimpleNamespace(
            store_metric_receipt=lambda *_args: None,
            prior_run_for_prediction=lambda *_args: duplicate_of_run_id,
            store_resource_sample=lambda *_args: None,
            manual_intervention_count=lambda _session: 0,
        ),
    )
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(workflow, "_event", lambda *_args, **_kwargs: None)
    state = {
        "session_id": "s", "run_id": "run-1", "transform_dir": str(transform),
        "experiment_contract": {"hypothesis": "test"},
        "experiment_count": 3, "experiment_attempt_count": 9,
        "tier_receipts": [{
            "tier": 4, "status": "succeeded", "output_directory": str(tmp_path / "tier4"),
            "gpu_seconds": 0.0, "peak_gpu_memory_mb": None,
            "wall_seconds": 1.0, "peak_rss_mb": 10.0,
        }],
    }

    result = await workflow.evaluate(state)

    if expected_count is None:
        assert "experiment_count" not in result
        assert result["error_category"] == "behavior_unchanged"
        assert result["duplicate_prediction_run_id"] == "run-prior"
        assert workflow._route_evaluate(result) == "recover"
    else:
        assert result["experiment_count"] == expected_count
        assert result["error"] == ""
        assert workflow._route_evaluate(result) == "decide"
    assert state["experiment_attempt_count"] == 9


def test_contract_selection_rejects_persistent_proxy_row_limit(tmp_path: Path) -> None:
    workspace = tmp_path / "limited"
    experiment = workspace / "src/flowstate/training/experiment.py"
    config = workspace / "configs/experiments/candidate.yaml"
    experiment.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    experiment.write_text("def predict():\n    pass\n", encoding="utf-8")
    config.write_text(
        "model:\n  name: factorization_machine\ntraining:\n  loss: bce\n  maximum_rows: 100000\n",
        encoding="utf-8",
    )
    workflow = AutonomousResearchWorkflow(SimpleNamespace())
    contract = _minimal_contract(
        ["src/flowstate/training/experiment.py", "configs/experiments/candidate.yaml"]
    )

    with pytest.raises(ValueError, match="tier 4 must train and score every fixed-split row"):
        workflow._verify_contract_selection(workspace, contract)


@pytest.mark.asyncio
async def test_evaluation_alignment_failure_routes_to_recovery(monkeypatch) -> None:
    services = SimpleNamespace(recovery=RecoveryController())
    workflow = AutonomousResearchWorkflow(services)

    async def control_gate(_state):
        return None

    async def fail_alignment(_state):
        raise RuntimeError("prediction columns are not aligned")

    monkeypatch.setattr(workflow, "_control_gate", control_gate)
    monkeypatch.setattr(workflow, "_evaluate_once", fail_alignment)
    monkeypatch.setattr(workflow, "_event", lambda *_args, **_kwargs: None)

    result = await workflow.evaluate({"session_id": "s", "run_id": "r"})

    assert result["failure_stage"] == "evaluate"
    assert result["error_category"] == "schema_data"
    assert workflow._route_evaluate(result) == "recover"
