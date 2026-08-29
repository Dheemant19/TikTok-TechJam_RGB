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
from rigor_rs.recovery.controller import RecoveryController
from rigor_rs.reporting.finalizer import SubmissionFinalizer


def test_langgraph_contains_durable_research_loop() -> None:
    workflow = AutonomousResearchWorkflow(SimpleNamespace())
    nodes = set(workflow.graph.get_graph().nodes)
    assert {"prepare", "profile", "baseline", "research", "code", "execute", "evaluate", "decide", "recover"} <= nodes


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

    tier2_calls = []

    class FakeWorkspace:
        def create(self, experiment_id, parent):
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

    assert await workflow._behavior_unchanged_vs_baseline(transform_dir, dead_patch_output, 0) is True
    assert await workflow._behavior_unchanged_vs_baseline(transform_dir, real_patch_output, 0) is False
    # The reference run must be computed exactly once and reused for both checks.
    assert len(tier2_calls) == 1


@pytest.mark.asyncio
async def test_execute_short_circuits_before_expensive_tiers_on_dead_patch(tmp_path: Path, monkeypatch) -> None:
    from rigor_rs.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches, PatchProposal

    contract = ExperimentContract(
        experiment_id="E1", parent_run_id="B0", hypothesis="Pairwise BPR ranking loss for long_view",
        observed_evidence_ids=[], primary_change="swap to BPR", allowed_files=["a.py"],
        prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
        falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
        comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
        budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
        fallback_run_id="B0", recovery_attempt_limit=1,
    )
    proposal = PatchProposal(unified_diff="diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n", tests=[], explanation="x")

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tier3_called = {"value": False}
    scores = np.asarray([0.1, 0.2, 0.3], dtype=np.float32)

    class FakeFunnel:
        async def tier1(self, *_a, **_k):
            return SimpleNamespace(status="succeeded", model_dump=lambda mode: {}, error=None)

        async def tier2(self, workspace, transform_dir, config, output, seed):
            model_dir = output / "model"
            model_dir.mkdir(parents=True, exist_ok=True)
            np.save(model_dir / "valid_scores.npy", scores)
            return SimpleNamespace(status="succeeded", model_dump=lambda mode: {}, error=None)

        async def tier3(self, *_a, **_k):
            tier3_called["value"] = True
            return SimpleNamespace(status="succeeded", model_dump=lambda mode: {}, error=None)

    class FakeWorkspace:
        def create(self, experiment_id, parent):
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
        "touched_files": ["a.py"], "transform_dir": str(tmp_path / "transform"),
    }

    result = await workflow.execute(state)

    assert not tier3_called["value"]
    assert "no measurable change in training behavior" in result["error"]


@pytest.mark.asyncio
async def test_execute_contains_unhandled_exceptions_as_recoverable_errors(tmp_path: Path, monkeypatch) -> None:
    # An unhandled exception in the funnel (live: a SyntaxError raised by
    # tier1's bare compile() on agent-generated code) previously escaped this
    # graph node entirely -- LangGraph recorded an internal __error__ write and
    # the whole run died with no ledger event, no recovery, and no visible
    # failure. It must become a routed, recoverable error instead.
    from rigor_rs.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches, PatchProposal

    contract = ExperimentContract(
        experiment_id="E1", parent_run_id="B0", hypothesis="Pairwise BPR ranking loss for long_view",
        observed_evidence_ids=[], primary_change="swap to BPR", allowed_files=["a.py"],
        prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
        falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
        comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
        budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
        fallback_run_id="B0", recovery_attempt_limit=1,
    )
    proposal = PatchProposal(unified_diff="diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n", tests=[], explanation="x")

    class ExplodingFunnel:
        async def tier1(self, *_a, **_k):
            raise SyntaxError("unterminated string literal (detected at line 229)")

    services = SimpleNamespace(funnel=ExplodingFunnel(), artifacts=tmp_path / "artifacts")
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


def test_route_recovery_retries_unless_explicitly_stopped() -> None:
    workflow = AutonomousResearchWorkflow(SimpleNamespace())
    assert workflow._route_recovery({"stop": False}) == "research"
    assert workflow._route_recovery({"stop": True}) == "stop"


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
            from rigor_rs.agents.azure_foundry import AgentUsage
            from rigor_rs.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches
            contract = ExperimentContract(
                experiment_id="E2", parent_run_id="B0", hypothesis="A genuinely new mechanism, not repeated",
                observed_evidence_ids=[], primary_change="try something new", allowed_files=["a.py"],
                prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
                falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
                comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
                budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
                fallback_run_id="B0", recovery_attempt_limit=1,
            )
            return SimpleNamespace(value=contract, usage=AgentUsage(input_tokens=10, output_tokens=10, model_id="fake"))


    prior_contract = {"experiment_id": "E1", "hypothesis": "BPR pairwise loss", "primary_change": "swap loss to BPR"}

    services = SimpleNamespace(
        knowledge=SimpleNamespace(retrieval=FakeRetrieval()),
        agents=FakeAgents(),
        contract=SimpleNamespace(public_summary=lambda: {}),
        maximum_experiments=10, bedrock_input_limit=100_000, bedrock_output_limit=100_000,
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
        "experiment_count": 3, "agent_input_tokens": 0, "agent_output_tokens": 0,
        "recovery_attempt": 2,  # simulates an unrelated earlier failure's leftover count
    }

    failure_result = await workflow.research(base_state)
    assert failure_result["recovery_attempt"] == 0
    assert failure_result["error"]
    assert seen_contexts[-1]["runs"] == [prior_contract]

    fail_next["value"] = False
    success_result = await workflow.research({**base_state, "recovery_attempt": 2})
    assert success_result["recovery_attempt"] == 0
    assert success_result["error"] == ""


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
            from rigor_rs.agents.azure_foundry import AgentUsage
            from rigor_rs.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches
            contract = ExperimentContract(
                experiment_id="E2", parent_run_id="B0", hypothesis="Pairwise BPR ranking loss for long_view",
                observed_evidence_ids=[paper.content_hash], primary_change="swap to BPR", allowed_files=["a.py"],
                prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
                falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
                comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
                budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
                fallback_run_id="B0", recovery_attempt_limit=1,
            )
            return SimpleNamespace(value=contract, usage=AgentUsage(input_tokens=10, output_tokens=10, model_id="fake"))

    services = SimpleNamespace(
        knowledge=SimpleNamespace(retrieval=FakeRetrieval()),
        agents=FakeAgents(),
        contract=SimpleNamespace(public_summary=lambda: {}),
        maximum_experiments=10, bedrock_input_limit=100_000, bedrock_output_limit=100_000,
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
        "experiment_count": 0, "agent_input_tokens": 0, "agent_output_tokens": 0, "recovery_attempt": 0,
    }

    result = await workflow.research(state)

    assert result["error"] == ""
    assert result["experiment_contract"]["observed_evidence_ids"] == [paper.paper_id]
    assert "content_hash" not in seen_contexts[-1]["evidence"][0]


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
            from rigor_rs.agents.azure_foundry import AgentUsage
            from rigor_rs.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches
            contract = ExperimentContract(
                experiment_id="E2", parent_run_id="B0", hypothesis="Pairwise BPR ranking loss for long_view",
                observed_evidence_ids=["fabricated-paper-id"], primary_change="swap to BPR", allowed_files=["a.py"],
                prohibited_files=[], predicted_gauc_direction="up", predicted_ndcg_at_5_direction="up",
                falsifiers=["regression"], outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
                comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
                budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
                fallback_run_id="B0", recovery_attempt_limit=1,
            )
            return SimpleNamespace(value=contract, usage=AgentUsage(input_tokens=10, output_tokens=10, model_id="fake"))

    services = SimpleNamespace(
        knowledge=SimpleNamespace(retrieval=FakeRetrieval()),
        agents=FakeAgents(),
        contract=SimpleNamespace(public_summary=lambda: {}),
        maximum_experiments=10, bedrock_input_limit=100_000, bedrock_output_limit=100_000,
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
        "experiment_count": 0, "agent_input_tokens": 0, "agent_output_tokens": 0, "recovery_attempt": 0,
    }

    result = await workflow.research(state)

    assert "fabricated-paper-id" in result["error"]
    assert paper.paper_id in result["error"]


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
