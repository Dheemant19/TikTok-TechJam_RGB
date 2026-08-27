from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

import numpy as np
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from rigor_rs.agents.bedrock import BedrockAgentFactory
from rigor_rs.contract.challenge import ChallengeContract
from rigor_rs.contract.models import (
    ComponentStatus, DataArtifact, ExperimentContract, FrontierState, MetricReceipt,
    PatchProposal, ProfileConfig, SplitTaint, TransformSpec,
)
from rigor_rs.data.profiler import PreprocessorService, ProfilerService
from rigor_rs.evaluation.official import OfficialEvaluator
from rigor_rs.knowledge.runtime import KnowledgeRuntime
from rigor_rs.ledger.workflow import WorkflowLedger, canonical_hash, new_id
from rigor_rs.orchestration.frontier import FrontierManager
from rigor_rs.orchestration.workspace import WorkspaceManager
from rigor_rs.recovery.controller import RecoveryController
from rigor_rs.training.baseline import BaselineReproducer
from rigor_rs.training.execution import ExecutionFunnel


class WorkflowState(TypedDict, total=False):
    session_id: str
    run_id: str
    status: str
    dataset_artifact: dict[str, Any]
    profile_receipt: dict[str, Any]
    transform_receipt: dict[str, Any]
    transform_dir: str
    baseline_result: dict[str, Any]
    baseline_metric: dict[str, Any]
    best_metric: dict[str, Any]
    parent_metric: dict[str, Any]
    frontier: dict[str, Any]
    experiment_count: int
    experiment_contract: dict[str, Any]
    patch_proposal: dict[str, Any]
    workspace: str
    worktree_commit: str
    touched_files: list[str]
    tier_receipts: list[dict[str, Any]]
    metric_receipt: dict[str, Any]
    agent_input_tokens: int
    agent_output_tokens: int
    error: str
    recovery_attempt: int
    stop: bool
    stop_reason: str


@dataclass
class WorkflowServices:
    contract: ChallengeContract
    ledger: WorkflowLedger
    profiler: ProfilerService
    preprocessor: PreprocessorService
    baseline: BaselineReproducer
    agents: BedrockAgentFactory
    knowledge: KnowledgeRuntime
    workspace: WorkspaceManager
    funnel: ExecutionFunnel
    evaluator: OfficialEvaluator
    frontier: FrontierManager
    recovery: RecoveryController
    repository: Path
    artifacts: Path
    maximum_experiments: int
    bedrock_input_limit: int
    bedrock_output_limit: int


class AutonomousResearchWorkflow:
    def __init__(self, services: WorkflowServices) -> None:
        self.s = services
        self.graph = self._build()

    def _event(self, state: WorkflowState, component: str, stage: str, event_type: str, status: ComponentStatus, summary: str, payload: dict[str, Any] | None = None):
        return self.s.ledger.append_event(
            session_id=state["session_id"], run_id=state.get("run_id", "workflow"),
            component_id=component, execution_id=new_id("execution"), stage=stage,
            event_type=event_type, status=status, plain_summary=summary, payload=payload or {},
        )

    async def _control_gate(self, state: WorkflowState) -> None:
        while True:
            snapshot = self.s.ledger.snapshot(state["session_id"])
            if snapshot.cancelled:
                raise asyncio.CancelledError(f"session {state['session_id']} was cancelled")
            if snapshot.status != ComponentStatus.PAUSED:
                return
            await asyncio.sleep(0.5)

    async def prepare(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        self.s.contract.verify_hashes()
        source_files = [
            self.s.contract.dataset_dir / "log_standard_4_08_to_4_21_pure.csv",
            self.s.contract.dataset_dir / "log_standard_4_22_to_5_08_pure.csv",
        ]
        source_hash = canonical_hash({str(path): path.stat().st_size for path in source_files})
        artifact = DataArtifact(
            artifact_id=new_id("data"), path=self.s.contract.dataset_dir,
            taints={SplitTaint.TRAIN_FEATURES, SplitTaint.TRAIN_LABELS, SplitTaint.VALIDATION_FEATURES},
            row_count=sum(1 for _ in ()), schema_fingerprint="kuairand-dev-logs",
            source_hash=source_hash, code_hash=canonical_hash({"profiler": 1}), creation_receipt_id=new_id("receipt"),
        )
        self._event(state, "train_data", "prepare", "data_ready", ComponentStatus.SUCCEEDED, "Training and validation data contract locked")
        return {"dataset_artifact": artifact.model_dump(mode="json"), "status": "running"}

    async def profile(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        self._event(state, "data_profiler", "profile", "started", ComponentStatus.RUNNING, "Inspecting and preparing development data")
        artifact = DataArtifact.model_validate(state["dataset_artifact"])
        profile = self.s.profiler.profile(artifact, ProfileConfig())
        transform = self.s.preprocessor.fit_apply(artifact, TransformSpec())
        for value in (profile.profile, profile.visualization, transform.state, transform.spec, transform.receipt, *transform.materializations.values()):
            self.s.ledger.register_artifact(value)
        self._event(state, "data_profiler", "profile", "completed", ComponentStatus.SUCCEEDED, "Data profile and train-fitted transform saved", {"profile": profile.model_dump(mode="json"), "transform": transform.model_dump(mode="json")})
        return {
            "profile_receipt": profile.model_dump(mode="json"),
            "transform_receipt": transform.model_dump(mode="json"),
            "transform_dir": str(transform.receipt.path.parent),
        }

    async def baseline(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        self._event(state, "trainer", "baseline", "started", ComponentStatus.RUNNING, "Reproducing official FM baseline on validation")
        result = self.s.baseline.reproduce(Path(state["transform_dir"]))
        if result["status"] != "succeeded":
            self._event(state, "phase_guard", "baseline", "integrity_halt", ComponentStatus.BLOCKED, "Official FM baseline reproduction missed tolerance", result)
            return {"baseline_result": result, "error": "baseline reproduction failed", "stop": True, "stop_reason": "baseline_gate"}
        metrics = result["seeds"][0]["metrics"]
        frontier = self.s.frontier.register_baseline("B0")
        self._event(state, "ledger", "baseline", "frontier", ComponentStatus.SUCCEEDED, "B0 registered as validation best and stable fallback", {"frontier": frontier.model_dump(mode="json"), "baseline_result": result})
        return {
            "baseline_result": result, "baseline_metric": metrics, "best_metric": metrics,
            "parent_metric": metrics, "frontier": frontier.model_dump(mode="json"), "experiment_count": 0,
        }

    async def research(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        run_id = new_id("run")
        self._event(state, "knowledge_mcp", "research", "started", ComponentStatus.RUNNING, "Finding research evidence")
        profile_path = Path(state["profile_receipt"]["profile"]["path"])
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        card = await self.s.knowledge.retrieval.research_card("improve within-user GAUC and nDCG@5 for long_view", 6)
        evidence = [{
            "paper_id": item.paper.paper_id, "title": item.paper.title,
            "relevance_notes": item.paper.relevance_notes, "content_hash": item.paper.content_hash,
        } for item in [*card.supporting, *card.contradicting]]
        self._event(state, "knowledge_mcp", "research", "completed", ComponentStatus.SUCCEEDED, "Research evidence selected", {"evidence_ids": card.source_ids, "source_mode": card.meta.source_mode, "supporting": [item.model_dump(mode="json") for item in card.supporting], "contradicting": [item.model_dump(mode="json") for item in card.contradicting], "missing_evidence": card.missing_evidence})
        context = {
            "challenge": self.s.contract.public_summary(), "profile": profile,
            "runs": [], "frontier": state["frontier"],
            "remaining_budget": {
                "experiments": self.s.maximum_experiments - state.get("experiment_count", 0),
                "bedrock_input_tokens": self.s.bedrock_input_limit - state.get("agent_input_tokens", 0),
                "bedrock_output_tokens": self.s.bedrock_output_limit - state.get("agent_output_tokens", 0),
            },
            "evidence": evidence,
            "allowed_files": ["src/rigor_rs/models/experimental.py", "src/rigor_rs/training/experiment.py", "configs/experiments/bce_fm.yaml", "tests/workflow/test_experiment.py"],
            "prohibited_files": ["kuairand-starter-kit/evaluate.py", "kuairand-starter-kit/data.py", "kuairand-starter-kit/baseline_scores.json", "runs/", "state/"],
            "fallback_run_id": FrontierState.model_validate(state["frontier"]).stable_fallback,
        }
        result = await self.s.agents.research(context)
        contract: ExperimentContract = result.value
        if any(item not in card.source_ids for item in contract.observed_evidence_ids):
            raise ValueError("Research Agent cited evidence not supplied by MCP")
        self.s.ledger.store_contract(state["session_id"], contract.experiment_id, contract.model_dump(mode="json"))
        self._event(state, "scientist", "research", "plan", ComponentStatus.SUCCEEDED, "One bounded experiment selected", {"contract": contract.model_dump(mode="json"), "usage": result.usage.model_dump()})
        return {
            "run_id": run_id, "experiment_contract": contract.model_dump(mode="json"),
            "agent_input_tokens": state.get("agent_input_tokens", 0) + result.usage.input_tokens,
            "agent_output_tokens": state.get("agent_output_tokens", 0) + result.usage.output_tokens,
            "experiment_count": state.get("experiment_count", 0) + 1,
        }

    async def code(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        contract = ExperimentContract.model_validate(state["experiment_contract"])
        self._event(state, "coder", "patch", "started", ComponentStatus.RUNNING, "Generating isolated code change")
        workspace, parent_commit = self.s.workspace.create(contract.experiment_id, "HEAD")
        source_context = {}
        for relative in contract.allowed_files:
            path = workspace / relative
            if path.is_file() and path.stat().st_size < 40_000:
                source_context[relative] = path.read_text(encoding="utf-8", errors="replace")
        result = await self.s.agents.propose_patch(contract, {"source_context": source_context, "reference_code": ""})
        proposal: PatchProposal = result.value
        try:
            _, patch_hash, touched = self.s.workspace.apply(workspace, contract, proposal)
        except Exception as first:
            repair = await self.s.agents.propose_patch(contract, {"source_context": source_context, "reference_code": "", "apply_error": str(first)})
            proposal = repair.value
            result.usage.input_tokens += repair.usage.input_tokens
            result.usage.output_tokens += repair.usage.output_tokens
            _, patch_hash, touched = self.s.workspace.apply(workspace, contract, proposal)
        commit = self.s.workspace.commit(workspace, contract.experiment_id)
        self._event(state, "coder", "patch", "completed", ComponentStatus.SUCCEEDED, "Patch validated and committed in isolated worktree", {"patch_hash": patch_hash, "commit": commit, "parent_commit": parent_commit, "files": touched})
        return {
            "patch_proposal": proposal.model_dump(mode="json"), "workspace": str(workspace),
            "worktree_commit": commit, "touched_files": touched,
            "agent_input_tokens": state.get("agent_input_tokens", 0) + result.usage.input_tokens,
            "agent_output_tokens": state.get("agent_output_tokens", 0) + result.usage.output_tokens,
        }

    async def execute(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        contract = ExperimentContract.model_validate(state["experiment_contract"])
        proposal = PatchProposal.model_validate(state["patch_proposal"])
        workspace = Path(state["workspace"])
        output = self.s.artifacts / "runs" / contract.experiment_id
        receipts = []
        tier1 = await self.s.funnel.tier1(workspace, state["touched_files"], proposal.tests, output / "tier1")
        receipts.append(tier1.model_dump(mode="json"))
        self._event(state, "trainer", "execute", "tier1", ComponentStatus.SUCCEEDED if tier1.status == "succeeded" else ComponentStatus.FAILED, "Isolated worktree test tier", {"receipt": receipts[-1]})
        if tier1.status != "succeeded":
            return {"tier_receipts": receipts, "error": tier1.error or "tier1 failed"}
        config = workspace / "configs/experiments/bce_fm.yaml"
        tier2 = await self.s.funnel.tier2(workspace, Path(state["transform_dir"]), config, output / "tier2", 0)
        receipts.append(tier2.model_dump(mode="json"))
        self._event(state, "trainer", "execute", "tier2", ComponentStatus.SUCCEEDED if tier2.status == "succeeded" else ComponentStatus.FAILED, "Smoke-scale proxy run", {"receipt": receipts[-1]})
        if tier2.status != "succeeded":
            return {"tier_receipts": receipts, "error": tier2.error or "tier2 failed"}
        tier3 = await self.s.funnel.tier3(workspace, Path(state["transform_dir"]), config, output / "tier3", 0)
        receipts.append(tier3.model_dump(mode="json"))
        self._event(state, "trainer", "execute", "tier3", ComponentStatus.SUCCEEDED if tier3.status == "succeeded" else ComponentStatus.FAILED, "Bounded proxy-scale run", {"receipt": receipts[-1]})
        if tier3.status != "succeeded":
            return {"tier_receipts": receipts, "error": tier3.error or "tier3 failed"}
        tier4 = await self.s.funnel.tier4(workspace, Path(state["transform_dir"]), config, output / "tier4", 0)
        receipts.append(tier4.model_dump(mode="json"))
        self._event(state, "trainer", "execute", "tier4", ComponentStatus.SUCCEEDED if tier4.status == "succeeded" else ComponentStatus.FAILED, "Full-scale training run", {"receipt": receipts[-1]})
        if tier4.status != "succeeded":
            return {"tier_receipts": receipts, "error": tier4.error or "tier4 failed"}
        return {"tier_receipts": receipts, "error": ""}

    async def evaluate(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        contract = ExperimentContract.model_validate(state["experiment_contract"])
        output = self.s.artifacts / "runs" / contract.experiment_id / "tier4/model"
        scores = np.load(output / "valid_scores.npy")
        with np.load(Path(state["transform_dir"]) / "valid.npz", allow_pickle=False) as data:
            users, videos, labels = data["users"].tolist(), data["videos"].tolist(), data["y"].tolist()
        prediction = output / "predictions.csv"
        prediction_hash = self.s.evaluator.write_predictions(prediction, users, videos, scores)
        receipt = self.s.evaluator.score(
            run_id=state["run_id"], prediction_artifact_id=prediction_hash,
            config_hash=canonical_hash(state["experiment_contract"]), users=users, labels=labels, scores=scores,
        )
        self._event(state, "evaluator", "validation", "metric", ComponentStatus.SUCCEEDED, "Official validation metrics recorded", {"metrics": {"GAUC": receipt.gauc, "nDCG@5": receipt.ndcg_at_5, "primary": receipt.primary}})
        tier_receipts = state.get("tier_receipts", [])
        resource_totals = {
            "wall_seconds": sum(item.get("wall_seconds", 0.0) for item in tier_receipts),
            "peak_rss_mb": max((item.get("peak_rss_mb", 0.0) for item in tier_receipts), default=0.0),
            "peak_gpu_memory_mb": max((item.get("peak_gpu_memory_mb") or 0.0 for item in tier_receipts), default=0.0),
            "bedrock_input_tokens": state.get("agent_input_tokens", 0),
            "bedrock_output_tokens": state.get("agent_output_tokens", 0),
            "retries": state.get("recovery_attempt", 0),
            "manual_interventions": state.get("manual_interventions", 0),
        }
        self._event(state, "trainer", "resources", "usage", ComponentStatus.SUCCEEDED, "Resource usage recorded for this run", {"resources": resource_totals})
        return {"metric_receipt": receipt.model_dump(mode="json")}

    async def decide(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        frontier = FrontierState.model_validate(state["frontier"])
        receipt = MetricReceipt.model_validate(state["metric_receipt"])
        best = MetricReceipt.model_validate(state["best_metric"])
        parent = MetricReceipt.model_validate(state["parent_metric"])
        updated, decision, converged = self.s.frontier.decide(frontier, receipt, state["run_id"], best, parent)
        budget_stop = (
            state["experiment_count"] >= self.s.maximum_experiments
            or state.get("agent_input_tokens", 0) >= self.s.bedrock_input_limit
            or state.get("agent_output_tokens", 0) >= self.s.bedrock_output_limit
        )
        stop = converged or budget_stop
        if stop:
            updated = self.s.frontier.budget_stop(updated)
        self._event(state, "watchdog", "decision", "frontier", ComponentStatus.SUCCEEDED if stop else ComponentStatus.READY, f"Experiment {decision}", {"frontier": updated.model_dump(mode="json"), "decision": decision, "converged": converged, "budget_stop": budget_stop, "experiment_id": ExperimentContract.model_validate(state["experiment_contract"]).experiment_id})
        values: dict[str, Any] = {"frontier": updated.model_dump(mode="json"), "stop": stop, "stop_reason": "convergence" if converged else ("budget" if budget_stop else "")}
        if updated.validation_best == state["run_id"]:
            values.update({"best_metric": state["metric_receipt"], "parent_metric": state["metric_receipt"]})
        return values

    async def recover(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        attempt = state.get("recovery_attempt", 0) + 1
        contract = ExperimentContract.model_validate(state["experiment_contract"])
        receipt = self.s.recovery.recover(state["run_id"], state["error"], attempt, contract.recovery_attempt_limit)
        self._event(state, "recovery", "recovery", "recovery", ComponentStatus.FAILED if attempt > contract.recovery_attempt_limit else ComponentStatus.READY, receipt.action, receipt.model_dump(mode="json"))
        if attempt > contract.recovery_attempt_limit or receipt.category == "metric_regression":
            frontier = FrontierState.model_validate(state["frontier"])
            frontier.failed.append(state["run_id"])
            return {"recovery_attempt": attempt, "error": "", "frontier": frontier.model_dump(mode="json"), "stop": state["experiment_count"] >= self.s.maximum_experiments}
        return {"recovery_attempt": attempt, "error": ""}

    def _route_baseline(self, state: WorkflowState) -> str:
        return "stop" if state.get("stop") else "research"

    def _route_execute(self, state: WorkflowState) -> str:
        return "recover" if state.get("error") else "evaluate"

    def _route_decide(self, state: WorkflowState) -> str:
        return "stop" if state.get("stop") else "research"

    def _route_recovery(self, state: WorkflowState) -> str:
        return "stop" if state.get("stop") else "research"

    def _build(self, checkpointer=None):
        graph = StateGraph(WorkflowState)
        for name in ("prepare", "profile", "baseline", "research", "code", "execute", "evaluate", "decide", "recover"):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "prepare")
        graph.add_edge("prepare", "profile")
        graph.add_edge("profile", "baseline")
        graph.add_conditional_edges("baseline", self._route_baseline, {"research": "research", "stop": END})
        graph.add_edge("research", "code")
        graph.add_edge("code", "execute")
        graph.add_conditional_edges("execute", self._route_execute, {"recover": "recover", "evaluate": "evaluate"})
        graph.add_edge("evaluate", "decide")
        graph.add_conditional_edges("decide", self._route_decide, {"research": "research", "stop": END})
        return graph.compile(checkpointer=checkpointer)

    async def run(self, session_id: str) -> WorkflowState:
        initial: WorkflowState = {
            "session_id": session_id, "run_id": "workflow", "status": "running",
            "agent_input_tokens": 0, "agent_output_tokens": 0, "experiment_count": 0,
            "recovery_attempt": 0, "stop": False,
        }
        checkpoint_path = self.s.ledger.database.with_name("langgraph.sqlite3")
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            await saver.setup()
            durable_graph = self._build(checkpointer=saver)
            return await durable_graph.ainvoke(
                initial,
                config={"configurable": {"thread_id": session_id}},
            )
