from __future__ import annotations

import ast
import asyncio
import json
import re
import time
from datetime import UTC, datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

import numpy as np
import yaml
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from flowstate.agents.azure_foundry import AzureAgentFactory, ExperimentScopeError
from flowstate.contract.challenge import ChallengeContract, sha256_file
from flowstate.contract.models import (
    ComponentStatus, DataArtifact, ExperimentContract, FrontierState, MetricReceipt,
    PatchProposal, ProfileConfig, SplitTaint, TransformSpec,
)
from flowstate.data.profiler import PreprocessorService, ProfilerService
from flowstate.evaluation.official import OfficialEvaluator
from flowstate.knowledge.runtime import KnowledgeRuntime
from flowstate.knowledge.models import EvidenceFilters
from flowstate.ledger.workflow import WorkflowLedger, canonical_hash, new_id
from flowstate.orchestration.frontier import FrontierManager
from flowstate.orchestration.workspace import WorkspaceManager
from flowstate.recovery.controller import RecoveryController
from flowstate.training.baseline import BaselineReproducer
from flowstate.training.execution import ExecutionFunnel


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
    error_category: str
    failure_stage: str
    experiment_count: int
    experiment_attempt_count: int
    recovery_attempt: int
    last_execution_error: str
    recovery_action: str
    retry_target: str
    stop: bool
    stop_reason: str
    started_at: float
    gpu_seconds_used: float


@dataclass
class WorkflowServices:
    contract: ChallengeContract
    ledger: WorkflowLedger
    profiler: ProfilerService
    preprocessor: PreprocessorService
    baseline: BaselineReproducer
    agents: AzureAgentFactory
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
    total_wall_seconds: int = 0
    total_gpu_hours: float = 0.0


class AutonomousResearchWorkflow:
    CODE_STAGE_TIMEOUT_SECONDS = 600.0

    def __init__(self, services: WorkflowServices) -> None:
        self.s = services
        self.graph = self._build()
        # One proxy-scale reference run per session, computed lazily and
        # reused for every experiment: cheap enough (tier2 is the fastest
        # tier) to fund a fast falsification check that a patch which
        # compiles, passes tests, and trains can still be functionally dead
        # code (new capability never wired into the actual model/loss call
        # sites) -- catches this before the expensive tier3/tier4 runs.
        self._reference_tier2_scores: dict[tuple[str, int], np.ndarray | None] = {}

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

    def _prior_run_summaries(
        self,
        session_id: str,
        prior_contracts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Join immutable plans with the execution evidence later runs need."""
        events_method = getattr(self.s.ledger, "events", None)
        events = events_method(session_id) if callable(events_method) else []
        by_experiment: dict[str, dict[str, Any]] = {}
        run_to_experiment: dict[str, str] = {}

        for event in events:
            if event.component_id != "scientist" or event.event_type != "plan":
                continue
            contract = event.payload.get("contract")
            if not isinstance(contract, dict) or not contract.get("experiment_id"):
                continue
            experiment_id = str(contract["experiment_id"])
            run_to_experiment[event.run_id] = experiment_id
            by_experiment[experiment_id] = {
                "run_id": event.run_id,
                "outcome": "planned",
                "failure_stage": None,
                "failure_category": None,
                "failure_summary": None,
                "recovery_action": None,
                "retry_target": None,
            }

        for event in events:
            experiment_id = run_to_experiment.get(event.run_id)
            if not experiment_id:
                continue
            summary = by_experiment[experiment_id]
            if event.component_id == "coder" and event.status == ComponentStatus.FAILED:
                summary.update(
                    outcome="code_failed",
                    failure_stage="code",
                    failure_summary=event.plain_summary,
                )
            elif event.component_id == "recovery":
                category = event.payload.get("category")
                summary.update(
                    outcome=(
                        "abandoned_after_code_timeout"
                        if category == "code_stage_timeout"
                        else "abandoned_after_scope_rejection"
                        if category == "experiment_scope"
                        else "retrying"
                    ),
                    failure_category=category,
                    recovery_action=event.plain_summary,
                    retry_target=event.payload.get("retry_target"),
                )
            elif event.component_id == "evaluator" and event.status == ComponentStatus.SUCCEEDED:
                summary["outcome"] = "evaluated"
            elif event.component_id == "watchdog" and event.stage == "decision":
                summary["outcome"] = event.payload.get("decision", "decided")

        empty_outcome = {
            "run_id": None,
            "outcome": "unknown",
            "failure_stage": None,
            "failure_category": None,
            "failure_summary": None,
            "recovery_action": None,
            "retry_target": None,
        }
        return [
            {
                "experiment_id": contract.get("experiment_id"),
                "hypothesis": contract.get("hypothesis"),
                "primary_change": contract.get("primary_change"),
                **by_experiment.get(str(contract.get("experiment_id")), empty_outcome),
            }
            for contract in prior_contracts
        ]

    async def prepare(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        self.s.contract.verify_hashes()
        source_files = [
            self.s.contract.dataset_dir / "log_standard_4_08_to_4_21_pure.csv",
            self.s.contract.dataset_dir / "log_standard_4_22_to_5_08_pure.csv",
        ]
        source_hash = canonical_hash({str(path): sha256_file(path) for path in source_files})
        artifact = DataArtifact(
            artifact_id=new_id("data"), path=self.s.contract.dataset_dir,
            taints={SplitTaint.TRAIN_FEATURES, SplitTaint.TRAIN_LABELS, SplitTaint.VALIDATION_FEATURES},
            row_count=sum(1 for _ in ()), schema_fingerprint="kuairand-dev-logs",
            source_hash=source_hash,
            code_hash=sha256_file(self.s.repository / "src/flowstate/data/profiler.py"),
            creation_receipt_id=new_id("receipt"),
        )
        self._event(
            state, "train_data", "prepare", "data_ready", ComponentStatus.SUCCEEDED,
            "Training and validation data contract locked",
            {
                "splits": {name: f"{lo}-{hi}" for name, (lo, hi) in self.s.contract.splits.items()},
                "source_hash": source_hash,
                "label": self.s.contract.label,
            },
        )
        # Every experiment's research() call now requires cited evidence to
        # carry verified code (EvidenceFilters(require_code=True)) so the
        # Code Agent always has a real implementation to port from. The
        # curated bank must be resolved once, up front -- Hugging Face
        # Papers discovery (research()'s live per-experiment source) is
        # hard-checked for a repository at query time instead, but the
        # curated bank's own declared repositories are static JSON until
        # something actually resolves them via GitHub, so this must run
        # before the first research() call, not left as declared-but-
        # unverified JSON. Logged under `train_data` (this is still data
        # preparation, not an experiment-decision event) so it groups with
        # "Training and validation data contract locked" in the Autonomy
        # Log, and -- critically -- never touches the "Save Run Evidence"
        # (`ledger`) card's status: that card's own real "Succeeded" only
        # ever fires much later, when B0 is actually registered as the
        # frontier baseline.
        curated_receipts = await self.s.knowledge.ingestion.ensure_curated_bank()
        if curated_receipts:
            self._event(
                state, "train_data", "prepare", "curated_bank_ready", ComponentStatus.SUCCEEDED,
                f"Resolved verified GitHub repositories for {len(curated_receipts)} curated papers",
                {"receipts": [receipt.model_dump(mode="json") for receipt in curated_receipts]},
            )
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
        try:
            result = await asyncio.to_thread(
                self.s.baseline.reproduce,
                Path(state["transform_dir"]),
            )
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            self._event(
                state, "trainer", "baseline", "failed", ComponentStatus.FAILED,
                f"Official FM baseline execution failed: {message}",
                {"error": message},
            )
            return {
                "error": message, "stop": True, "stop_reason": "baseline_failure",
            }
        if result["status"] != "succeeded":
            self._event(state, "phase_guard", "baseline", "integrity_halt", ComponentStatus.BLOCKED, "Official FM baseline reproduction missed tolerance", result)
            return {"baseline_result": result, "error": "baseline reproduction failed", "stop": True, "stop_reason": "baseline_gate"}

        # Every downstream decision compares against this value (decide() builds
        # its MetricReceipt comparator straight from state["best_metric"]/
        # "parent_metric"), so it must be the same 5-seed mean the UI already
        # shows as "the baseline" -- using seeds[0] alone silently compared
        # every experiment against one arbitrary noisy seed instead of the
        # stable aggregate the reproduction was designed to produce.
        metrics = self._average_seed_metrics([entry["metrics"] for entry in result["seeds"]])
        # Persist successful baseline evidence before running secondary sanity
        # controls. The 2026-08-30 Windows failure happened after all five FM
        # seeds completed; because this was previously deferred, the UI falsely
        # looked as though the baseline itself had never computed.
        for seed_result in result["seeds"]:
            metric = seed_result["metrics"]
            self.s.ledger.store_metric_receipt(
                state["session_id"], metric["run_id"], metric
            )
        self._event(
            state, "trainer", "baseline", "completed", ComponentStatus.SUCCEEDED,
            "Official FM baseline reproduced within organizer tolerance",
            {"baseline_result": result},
        )

        self._event(
            state, "phase_guard", "baseline", "sanity_checks", ComponentStatus.RUNNING,
            "Running evaluator harness and label-shuffle safety checks",
            {"checks": ["harness", "label_shuffle"]},
        )

        transform_dir = Path(state["transform_dir"])
        try:
            harness = await asyncio.to_thread(self.s.baseline.harness_checks, transform_dir)
            shuffle = await asyncio.to_thread(self.s.baseline.label_shuffle_control, transform_dir)
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            self._event(
                state, "phase_guard", "baseline", "failed", ComponentStatus.FAILED,
                f"Pipeline sanity checks failed to execute: {message}",
                {"error": message, "baseline_result": result},
            )
            return {
                "baseline_result": result, "baseline_metric": metrics,
                "error": message, "stop": True, "stop_reason": "baseline_failure",
            }
        sanity = {
            "harness": {name: receipt.model_dump(mode="json") for name, receipt in harness.items()},
            "label_shuffle": shuffle,
        }
        if not shuffle["passed"]:
            self._event(
                state, "phase_guard", "baseline", "integrity_halt", ComponentStatus.BLOCKED,
                "Label-shuffle negative control scored above the random bound; halting before novel experiments",
                sanity,
            )
            return {
                "baseline_result": result, "error": "pipeline sanity check failed",
                "stop": True, "stop_reason": "baseline_gate",
            }
        self._event(
            state, "phase_guard", "baseline", "sanity_checks", ComponentStatus.SUCCEEDED,
            "Pipeline sanity checks passed: shuffled training labels score no better than random",
            sanity,
        )
        frontier = self.s.frontier.register_baseline("B0")
        self.s.ledger.store_frontier(state["session_id"], frontier)
        self._event(state, "ledger", "baseline", "frontier", ComponentStatus.SUCCEEDED, "B0 registered as validation best and stable fallback", {"frontier": frontier.model_dump(mode="json"), "baseline_result": result})
        return {
            "baseline_result": result, "baseline_metric": metrics, "best_metric": metrics,
            "parent_metric": metrics, "frontier": frontier.model_dump(mode="json"), "experiment_count": 0,
        }

    @staticmethod
    def _average_seed_metrics(receipts: list[dict[str, Any]]) -> dict[str, Any]:
        """Aggregate N per-seed metric receipts into the single stable comparator
        every experiment is judged against. gauc/ndcg_at_5/primary are averaged;
        evaluator_hash, config_hash, users, rows, and scope are structural (same
        split, same evaluator) and are taken verbatim from the first receipt --
        they are asserted identical across seeds rather than silently trusted.
        """
        if not receipts:
            raise ValueError("cannot average zero baseline seed receipts")
        first = receipts[0]
        for entry in receipts[1:]:
            if entry["evaluator_hash"] != first["evaluator_hash"] or entry["config_hash"] != first["config_hash"]:
                raise ValueError("baseline seeds used different evaluator/config -- not directly comparable")
        document = {
            "receipt_id": new_id("receipt"), "run_id": "B0",
            "prediction_artifact_id": first["prediction_artifact_id"],
            "evaluator_hash": first["evaluator_hash"], "config_hash": first["config_hash"],
            "gauc": sum(entry["gauc"] for entry in receipts) / len(receipts),
            "ndcg_at_5": sum(entry["ndcg_at_5"] for entry in receipts) / len(receipts),
            "primary": sum(entry["primary"] for entry in receipts) / len(receipts),
            "users": first["users"], "rows": first["rows"],
            "comparable": True, "scope": "validation",
            "occurred_at": datetime.now(UTC).isoformat(),
        }
        return {**document, "receipt_hash": canonical_hash(document)}

    def _budget_exhausted(self, state: WorkflowState) -> str:
        """Name the exhausted budget, or an empty string while work may continue."""
        if state.get("experiment_count", 0) >= self.s.maximum_experiments:
            return f"completed validation experiment budget reached ({self.s.maximum_experiments})"
        if state.get("agent_input_tokens", 0) >= self.s.bedrock_input_limit:
            return "LLM input token budget reached"
        if state.get("agent_output_tokens", 0) >= self.s.bedrock_output_limit:
            return "LLM output token budget reached"
        gpu_hours_used = state.get("gpu_seconds_used", 0.0) / 3600
        if self.s.total_gpu_hours and gpu_hours_used >= self.s.total_gpu_hours:
            return f"GPU-hour budget reached ({gpu_hours_used:.3f}/{self.s.total_gpu_hours})"
        started = state.get("started_at")
        if started and self.s.total_wall_seconds:
            elapsed = time.time() - float(started)
            if elapsed >= self.s.total_wall_seconds:
                return f"wall-clock budget reached ({self.s.total_wall_seconds}s)"
        return ""

    # Ordered exactly as AGENTS.md's "High-Value KuaiRand Research Directions"
    # priority list. Rotated by completed-contract count within the session so
    # each successive experiment targets a different mechanism family instead
    # of the single hardcoded query below always retrieving the same ~6
    # papers -- reproduced live: 69 contracts across 22 sessions cited only 5
    # distinct paper_ids total, out of 20 curated papers spanning all 7 areas.
    _PRIORITY_AREA_ROTATION = (
        "ranking_loss_alignment", "sequential_user_modeling", "multi_task_learning",
        "watch_time_censored_regression", "feature_interaction_architectures",
        "temporal_drift_modeling", "off_policy_validation",
    )
    _PRIORITY_AREA_QUERIES = {
        "ranking_loss_alignment": "pairwise or listwise ranking loss aligned with GAUC and nDCG@5 instead of pointwise BCE",
        "sequential_user_modeling": "sequential user history and short-term interest modeling for within-user ranking",
        "multi_task_learning": "multi-task learning with auxiliary engagement signals for long_view ranking",
        "watch_time_censored_regression": "censored watch-time and duration-bias regression for engagement ranking",
        "feature_interaction_architectures": "explicit feature interaction architectures for click-through and engagement ranking",
        "temporal_drift_modeling": "temporal dynamics and train/test distribution drift in recommendation ranking",
        "off_policy_validation": "unbiased off-policy evaluation and exposure bias correction for ranking",
    }

    async def research(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        # Budget checks must run before every paid research call, not only after
        # a successful validation decision. Failed code attempts do not consume
        # completed-experiment slots, but they remain bounded by per-contract
        # recovery caps plus the session's token, wall-clock, GPU-hour and
        # provider-request limits.
        exhausted = self._budget_exhausted(state)
        if exhausted:
            frontier = self.s.frontier.budget_stop(FrontierState.model_validate(state["frontier"]))
            self.s.ledger.store_frontier(state["session_id"], frontier)
            self._event(
                state, "watchdog", "decision", "frontier", ComponentStatus.SUCCEEDED,
                f"Stopping before a new experiment: {exhausted}",
                {
                    "frontier": frontier.model_dump(mode="json"), "decision": "budget_stop",
                    "converged": False, "budget_stop": True, "reason": exhausted,
                },
            )
            return {
                "frontier": frontier.model_dump(mode="json"),
                "stop": True, "stop_reason": "budget", "error": "",
            }
        run_id = new_id("run")
        event_state = {**state, "run_id": run_id}
        self._event(event_state, "knowledge_mcp", "research", "started", ComponentStatus.RUNNING, "Finding research evidence")
        profile_path = Path(state["profile_receipt"]["profile"]["path"])
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        prior_contracts = self.s.ledger.list_contracts(state["session_id"])
        area = self._PRIORITY_AREA_ROTATION[len(prior_contracts) % len(self._PRIORITY_AREA_ROTATION)]
        card = await self.s.knowledge.retrieval.research_card(
            self._PRIORITY_AREA_QUERIES[area], 6,
            session_id=state["session_id"], experiment_id=run_id,
            # The Code Agent can only port an idea from a real, pinned,
            # license-verified repository (get_code_for_paper/search_code
            # never return unverified records). Requiring verified code here
            # -- for curated evidence as well as any live-discovered paper --
            # means every cited paper_id is actually implementable, instead
            # of the Research Agent selecting a paper whose repository was
            # never resolved (or that has none at all) and the Code Agent
            # then finding "No reference code" on every single attempt.
            filters=EvidenceFilters(require_code=True),
            # bypass_cache=True: this is the once-per-experiment call that
            # picks the actual hypothesis, not a cheap lookup -- it must go
            # find current evidence every time, not replay whatever the first
            # call for this (area, day) pair happened to return up to 7 days
            # ago (cache_ttl_seconds=604800).
            bypass_cache=True,
        )
        # content_hash is deliberately excluded here: sending it as a sibling
        # hash-like field next to paper_id caused the model to periodically
        # cite content_hash instead of paper_id (reproduced live: ~40% of
        # calls). alias_to_paper_id still lets a genuine same-item mix-up
        # (paper_id vs content_hash) self-correct instead of burning a full
        # recovery retry, without accepting any value not traceable to a
        # real supplied evidence item.
        evidence = [{
            "paper_id": item.paper.paper_id, "title": item.paper.title,
            "source": getattr(item.paper, "trust_tier", "unknown"),
            "relevance_notes": item.paper.relevance_notes,
        } for item in [*card.supporting, *card.contradicting]]
        alias_to_paper_id = {
            item.paper.content_hash: item.paper.paper_id
            for item in [*card.supporting, *card.contradicting]
        }
        retrieval_config = getattr(
            getattr(self.s.knowledge.retrieval, "config", None),
            "retrieval",
            None,
        )
        curated_bank_share = float(getattr(retrieval_config, "curated_bank_share", 0.5))
        self._event(event_state, "knowledge_mcp", "research", "completed", ComponentStatus.SUCCEEDED, "Research evidence selected", {"evidence_ids": card.source_ids, "source_mode": card.meta.source_mode, "supporting": [item.model_dump(mode="json") for item in card.supporting], "contradicting": [item.model_dump(mode="json") for item in card.contradicting], "missing_evidence": card.missing_evidence})
        execution = getattr(self.s, "execution", None)
        proxy_config = getattr(execution, "proxy_config", {})
        per_run_timeout = int(getattr(execution, "timeout_seconds", 5400))
        proxy_wall_seconds = min(
            int(proxy_config.get("maximum_wall_seconds", 600)),
            per_run_timeout,
        )
        context = {
            "challenge": self.s.contract.public_summary(), "profile": profile,
            "runs": self._prior_run_summaries(state["session_id"], prior_contracts),
            "frontier": state["frontier"],
            "remaining_budget": {
                "experiments": self.s.maximum_experiments - state.get("experiment_count", 0),
                "bedrock_input_tokens": self.s.bedrock_input_limit - state.get("agent_input_tokens", 0),
                "bedrock_output_tokens": self.s.bedrock_output_limit - state.get("agent_output_tokens", 0),
            },
            "execution_constraints": {
                "code_writing_wall_seconds": int(self.CODE_STAGE_TIMEOUT_SECONDS),
                "code_output_mode": "complete replacement contents for every changed file",
                "code_tools_available": False,
                "preferred_maximum_production_files": 2,
                "fast_proxy_rows": int(proxy_config.get("maximum_rows", 100_000)),
                "fast_proxy_wall_seconds": proxy_wall_seconds,
                "fast_proxy_gpu_hours": float(proxy_config.get("maximum_gpu_hours", 0.15)),
                "full_training_wall_seconds": per_run_timeout,
                "first_falsification_target": "minutes on the existing GPU proxy, not a long architecture build",
            },
            "evidence": evidence,
            "evidence_source_balance": {
                "curated_bank_share": curated_bank_share,
                "huggingface_share": 1.0 - curated_bank_share,
            },
            "allowed_files": ["src/flowstate/models/experimental.py", "src/flowstate/training/experiment.py", "configs/experiments/bce_fm.yaml", "tests/workflow/test_experiment.py"],
            "prohibited_files": ["kuairand-starter-kit/evaluate.py", "kuairand-starter-kit/data.py", "kuairand-starter-kit/baseline_scores.json", "runs/", "state/"],
            "fallback_run_id": FrontierState.model_validate(state["frontier"]).stable_fallback,
        }
        try:
            result = await self.s.agents.research(context)
            contract: ExperimentContract = result.value
            cited = [alias_to_paper_id.get(item, item) for item in contract.observed_evidence_ids]
            unresolved = [item for item in cited if item not in card.source_ids]
            if unresolved:
                raise ValueError(
                    f"Research Agent cited evidence not supplied by MCP: {unresolved} "
                    f"(valid ids: {card.source_ids})"
                )
            if cited != contract.observed_evidence_ids:
                contract = contract.model_copy(update={"observed_evidence_ids": cited})
        except Exception as error:
            self._event(event_state, "scientist", "research", "failed", ComponentStatus.FAILED, f"Research Agent call failed: {error}", {"error": str(error)})
            return {
                "run_id": run_id, "error": str(error),
                "error_category": self.s.recovery.classify(str(error)),
                "failure_stage": "research", "recovery_attempt": 0,
                "experiment_attempt_count": state.get("experiment_attempt_count", 0) + 1,
            }
        proposed_experiment_id = contract.experiment_id
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", proposed_experiment_id).strip("-._") or "experiment"
        contract = contract.model_copy(
            update={"experiment_id": f"{safe_name[:48]}-{run_id.rsplit('-', 1)[-1]}"}
        )
        self.s.ledger.store_contract(state["session_id"], contract.experiment_id, contract.model_dump(mode="json"))
        self._event(
            event_state, "scientist", "research", "plan", ComponentStatus.SUCCEEDED,
            "One bounded experiment selected",
            {
                "contract": contract.model_dump(mode="json"),
                "proposed_experiment_id": proposed_experiment_id,
                "planned_run_id": run_id,
                "usage": result.usage.model_dump(),
            },
        )
        return {
            "run_id": run_id, "experiment_contract": contract.model_dump(mode="json"), "error": "",
            "error_category": "", "failure_stage": "", "recovery_attempt": 0,
            "last_execution_error": "", "recovery_action": "", "retry_target": "",
            "agent_input_tokens": state.get("agent_input_tokens", 0) + result.usage.input_tokens,
            "agent_output_tokens": state.get("agent_output_tokens", 0) + result.usage.output_tokens,
            "experiment_attempt_count": state.get("experiment_attempt_count", 0) + 1,
        }

    async def _propose_patch_before_deadline(
        self,
        contract: ExperimentContract,
        context: dict[str, Any],
        deadline: float,
    ) -> Any:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Code Agent exceeded the {int(self.CODE_STAGE_TIMEOUT_SECONDS)}-second code-writing limit"
            )
        try:
            return await asyncio.wait_for(
                self.s.agents.propose_patch(
                    contract,
                    {**context, "code_writing_seconds_remaining": max(1, int(remaining))},
                ),
                timeout=remaining,
            )
        except asyncio.TimeoutError as error:
            raise TimeoutError(
                f"Code Agent exceeded the {int(self.CODE_STAGE_TIMEOUT_SECONDS)}-second code-writing limit"
            ) from error

    async def code(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        contract = ExperimentContract.model_validate(state["experiment_contract"])
        self._event(state, "coder", "patch", "started", ComponentStatus.RUNNING, "Generating isolated code change")
        # Worktrees are namespaced by the system-assigned contract ID. The
        # Research Agent often reuses human-friendly IDs such as "E1"; using
        # those values directly previously collided with worktrees and ledger
        # rows from earlier sessions.
        retry_attempt = state.get("recovery_attempt", 0)
        workspace_name = (
            contract.experiment_id
            if retry_attempt == 0
            else f"{contract.experiment_id}-retry{retry_attempt}"
        )
        workspace, parent_commit = self.s.workspace.create(
            workspace_name,
            "HEAD",
            required_paths=contract.allowed_files,
        )
        source_context = {}
        for relative in contract.allowed_files:
            path = workspace / relative
            if path.is_file() and not path.is_symlink():
                source_context[relative] = path.read_text(encoding="utf-8", errors="replace")
        remaining_output_tokens = max(
            0,
            self.s.bedrock_output_limit - state.get("agent_output_tokens", 0),
        )
        reference_code, reference_repositories = await self.s.knowledge.retrieval.reference_code_for_experiment(
            contract.observed_evidence_ids, contract.primary_change,
            session_id=state["session_id"], experiment_id=state.get("run_id", contract.experiment_id),
        )
        # Finding no reference code (a paper with no cited repository, or a
        # fallback search that turns up nothing) is an expected, non-fatal
        # outcome the Code Agent is designed to proceed without -- it is not
        # a failure of the "Write the Code Change" stage, which is still
        # actively running its own LLM call at this point (`propose_patch`
        # below can take far longer than this lookup). Reporting it as
        # ComponentStatus.FAILED previously froze the coder card on "Failed"
        # for that entire stretch, and separately caused Experiments' failed-
        # run detection (component_id "coder" + status "failed") to
        # misclassify runs that went on to complete normally. RUNNING keeps
        # the card accurate: this is a checkpoint inside ongoing work, not a
        # terminal state either way.
        self._event(
            state, "coder", "patch", "reference_code", ComponentStatus.RUNNING,
            f"Reference code search found {len(reference_repositories)} repositories" if reference_repositories
            else "No reference code found for the cited papers or fallback search",
            {"repositories": reference_repositories, "characters": len(reference_code)},
        )
        agent_context = {
            "source_context": source_context,
            "reference_code": reference_code,
            "reference_code_available": bool(reference_code),
            "reference_code_repositories": reference_repositories,
            "remaining_output_tokens": remaining_output_tokens,
            "execution_constraints": {
                "total_code_stage_wall_seconds": int(self.CODE_STAGE_TIMEOUT_SECONDS),
                "output_mode": "complete replacement contents for changed files",
                "tools_available": False,
                "scope": "one immutable experiment; minimal faithful implementation only",
            },
            "previous_execution_failure": state.get("last_execution_error") or None,
            "required_recovery_action": state.get("recovery_action") or None,
        }
        code_deadline = time.monotonic() + self.CODE_STAGE_TIMEOUT_SECONDS
        try:
            result = await self._propose_patch_before_deadline(
                contract, agent_context, code_deadline
            )
            proposal: PatchProposal = result.value
            activated: str | None = None
            try:
                _, patch_hash, touched = self.s.workspace.apply(workspace, contract, proposal)
                self._verify_training_entrypoint(workspace)
                self._verify_new_symbols_wired(workspace, contract)
                activated = self._activate_patch_capability(
                    workspace,
                    source_context.get("src/flowstate/training/experiment.py", ""),
                )
            except Exception as first:
                # Validation may fail after git apply has already changed the
                # worktree. Restore the exact source snapshot before asking for
                # a repaired full-file proposal; otherwise its deterministic
                # diff is built against source_context but applied to the
                # partially patched files and git rejects the hunks.
                self.s.workspace.restore_sources(
                    workspace,
                    contract.allowed_files,
                    source_context,
                )
                repair = await self._propose_patch_before_deadline(
                    contract,
                    {
                        **agent_context,
                        "previous_proposal": proposal.model_dump(mode="json"),
                        "apply_error": str(first),
                        "remaining_output_tokens": max(
                            0,
                            remaining_output_tokens - result.usage.output_tokens,
                        ),
                    },
                    code_deadline,
                )
                proposal = repair.value
                result.usage.input_tokens += repair.usage.input_tokens
                result.usage.output_tokens += repair.usage.output_tokens
                _, patch_hash, touched = self.s.workspace.apply(workspace, contract, proposal)
                self._verify_training_entrypoint(workspace)
                self._verify_new_symbols_wired(workspace, contract)
                activated = self._activate_patch_capability(
                    workspace,
                    source_context.get("src/flowstate/training/experiment.py", ""),
                )
            if activated:
                touched = sorted({*touched, "configs/experiments/bce_fm.yaml"})
                self._event(
                    state, "coder", "patch", "activation", ComponentStatus.SUCCEEDED,
                    f"Selected the loss branch this patch introduced: training.loss={activated}",
                    {"activated_loss": activated},
                )
            commit = self.s.workspace.commit(
                workspace,
                contract.experiment_id,
                touched,
            )
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            category = (
                "code_stage_timeout"
                if isinstance(error, TimeoutError)
                else "experiment_scope"
                if isinstance(error, ExperimentScopeError)
                else self.s.recovery.classify(message)
            )
            self._event(state, "coder", "patch", "failed", ComponentStatus.FAILED, f"Code Agent call failed: {message}", {"error": message})
            return {
                "error": message, "error_category": category,
                "failure_stage": "code",
            }
        self._event(
            state, "coder", "patch", "completed", ComponentStatus.SUCCEEDED,
            "Patch validated and committed in isolated worktree",
            {
                "patch_hash": patch_hash, "commit": commit, "parent_commit": parent_commit,
                "files": touched, "workspace": str(workspace),
            },
        )
        return {
            "patch_proposal": proposal.model_dump(mode="json"), "workspace": str(workspace),
            "worktree_commit": commit, "touched_files": touched, "error": "",
            "error_category": "", "failure_stage": "",
            "agent_input_tokens": state.get("agent_input_tokens", 0) + result.usage.input_tokens,
            "agent_output_tokens": state.get("agent_output_tokens", 0) + result.usage.output_tokens,
        }

    def _verify_training_entrypoint(self, workspace: Path) -> None:
        """Reject a syntactically valid replacement that silently stops training."""
        relative = "src/flowstate/training/experiment.py"
        experiment = workspace / relative
        if not experiment.is_file():
            return
        source = experiment.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(experiment))
        functions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        has_main_guard = any(
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
            and len(node.test.comparators) == 1
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value == "__main__"
            and any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "main"
                for call in ast.walk(node)
            )
            for node in tree.body
        )
        required_artifacts = {"checkpoint.pt", "valid_scores.npy", "train_receipt.json"}
        string_literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        missing_functions = sorted({"train", "main"} - functions)
        missing_artifacts = sorted(required_artifacts - string_literals)
        if not missing_functions and not missing_artifacts and has_main_guard:
            return
        self.s.workspace.revert(workspace)
        problems = []
        if missing_functions:
            problems.append(f"missing top-level functions {missing_functions}")
        if not has_main_guard:
            problems.append("missing __main__ guard that calls main()")
        if missing_artifacts:
            problems.append(f"missing required artifact writes {missing_artifacts}")
        raise ValueError(
            f"{relative} no longer satisfies the executable training contract: "
            + "; ".join(problems)
            + ". Preserve the complete module and make a surgical change instead of replacing it with a truncated file."
        )

    _LOSS_BRANCH_PATTERN = re.compile(r'loss_name\s*==\s*["\']([^"\']+)["\']')

    def _activate_patch_capability(self, workspace: Path, original_source: str) -> str | None:
        """Deterministically select the loss branch a patch just introduced.

        train() picks its loss branch by comparing `loss_name` (read from
        configs/experiments/bce_fm.yaml) against string literals, so a patch
        adding `loss_name == "X"` without setting training.loss to X is dead
        code. Activating the one branch introduced by the current proposal is
        faithful execution of its declared primary change and is logged.

        `original_source` is the exact source snapshot supplied to the Code
        Agent. It must not be read from git HEAD: allowed files can contain
        deliberate uncommitted user changes that WorkspaceManager materializes
        into every experiment. Comparing against HEAD misclassified those
        existing branches as newly introduced and silently activated an
        unrelated loss for every later experiment.

        Exactly one genuinely new branch is unambiguous and is activated; more
        than one is returned for agent repair. A patch adding no branch is left
        untouched.
        """
        relative = "src/flowstate/training/experiment.py"
        experiment = workspace / relative
        config_path = workspace / "configs/experiments/bce_fm.yaml"
        if not experiment.is_file() or not config_path.is_file():
            return None
        patched = set(self._LOSS_BRANCH_PATTERN.findall(experiment.read_text(encoding="utf-8")))
        original = set(self._LOSS_BRANCH_PATTERN.findall(original_source))
        introduced = patched - original
        if not introduced:
            return None
        config_text = config_path.read_text(encoding="utf-8")
        training = (yaml.safe_load(config_text) or {}).get("training", {}) or {}
        if str(training.get("loss", "")) in patched:
            return None
        if len(introduced) > 1:
            self.s.workspace.revert(workspace)
            raise ValueError(
                f"ambiguous activation: this patch adds {sorted(introduced)} loss branches to train() but "
                f"configs/experiments/bce_fm.yaml selects none of them. Set training.loss to exactly the "
                f"branch this experiment should run, in this same patch."
            )
        branch = introduced.pop()
        # Replace the value in place rather than round-tripping the YAML, so the
        # file's comments and layout survive.
        updated, count = re.subn(r"(?m)^(\s*loss:\s*).*$", lambda m: f"{m.group(1)}{branch}", config_text, count=1)
        if count == 0:
            self.s.workspace.revert(workspace)
            raise ValueError(
                f"cannot activate {branch!r}: configs/experiments/bce_fm.yaml has no training.loss line to set."
            )
        config_path.write_text(updated, encoding="utf-8")
        return branch

    _TOP_LEVEL_SYMBOL_PATTERN = re.compile(r"(?m)^(?:class|def)\s+(\w+)")

    def _verify_new_symbols_wired(self, workspace: Path, contract: ExperimentContract) -> None:
        """Reject a patch that defines a new class/function nobody calls.

        _activate_patch_capability only closes the loss-branch-string variant of
        this failure (see its docstring). Every other capability shape -- a new
        model class, a new forward()/constructor argument, a new helper function
        -- has no safe deterministic auto-fix: wiring it in requires a real code
        decision (which call site, which arguments, how outputs combine) that is
        not safe to guess. Observed live and repeatedly in the ledger: MMoE heads,
        sequence encoders, and temporal-reweighting patches defining a fully
        correct new class/function in an allowed model file while never touching
        the training entrypoint's model construction or loss call sites, so the
        tier2 proxy run (a full GPU run) discovered a bit-identical ranking with
        only a generic error. This catches that dead-code shape immediately, for
        free, right after the patch is applied -- before any GPU time is spent --
        and forces the one bounded in-call repair retry with the exact unreferenced
        symbol and its defining file named, instead of a generic label.
        """
        relative = "src/flowstate/training/experiment.py"
        entrypoint = workspace / relative
        if not entrypoint.is_file():
            return
        entrypoint_text = entrypoint.read_text(encoding="utf-8")
        unwired: list[tuple[str, str]] = []
        for touched in contract.allowed_files:
            if touched in (relative, "configs/experiments/bce_fm.yaml") or touched.startswith("tests/"):
                continue
            path = workspace / touched
            if not path.is_file() or path.suffix != ".py":
                continue
            patched = set(self._TOP_LEVEL_SYMBOL_PATTERN.findall(path.read_text(encoding="utf-8")))
            try:
                head_source = self.s.workspace.file_at_head(workspace, touched)
            except Exception:
                head_source = ""
            original = set(self._TOP_LEVEL_SYMBOL_PATTERN.findall(head_source))
            for symbol in sorted(patched - original):
                if not re.search(rf"\b{re.escape(symbol)}\b", entrypoint_text):
                    unwired.append((symbol, touched))
        if not unwired:
            return
        self.s.workspace.revert(workspace)
        listed = "; ".join(f"{symbol!r} (defined in {file})" for symbol, file in unwired)
        raise ValueError(
            f"inert patch: patch defines new symbols that {relative} never references: {listed}. "
            "A new class or function that train() never imports or calls cannot change "
            "GAUC/nDCG@5 -- it is dead code. Import it and call it from the model "
            f"construction, forward, or loss call sites inside {relative} in this same "
            "patch, or delete it if it is not needed."
        )

    async def execute(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        try:
            return await self._execute_tiers(state)
        except Exception as error:
            # Any unhandled exception in the funnel (a SyntaxError in
            # agent-generated code, a missing artifact, a git failure)
            # previously escaped this graph node entirely: LangGraph recorded
            # an internal __error__ write and the whole run died with no
            # ledger event, no recovery, and no visible failure. Every
            # execution failure must become a recoverable, logged error.
            # asyncio.CancelledError derives from BaseException, so an
            # intentional session cancel is still not swallowed here.
            message = f"{type(error).__name__}: {error}"
            self._event(state, "trainer", "execute", "failed", ComponentStatus.FAILED, f"Execution funnel failed: {message}", {"error": message})
            return {
                "error": message, "error_category": self.s.recovery.classify(message),
                "failure_stage": "execute",
            }

    def _run_output(self, state: WorkflowState, contract: ExperimentContract) -> Path:
        return (
            self.s.artifacts
            / "runs"
            / state["session_id"]
            / state.get("run_id", contract.experiment_id)
            / f"attempt-{state.get('recovery_attempt', 0)}"
            / contract.experiment_id
        )

    async def _execute_tiers(self, state: WorkflowState) -> dict[str, Any]:
        contract = ExperimentContract.model_validate(state["experiment_contract"])
        proposal = PatchProposal.model_validate(state["patch_proposal"])
        workspace = Path(state["workspace"])
        output = self._run_output(state, contract)
        receipts = []
        tier1 = await self.s.funnel.tier1(workspace, state["touched_files"], proposal.tests, output / "tier1")
        receipts.append(tier1.model_dump(mode="json"))
        self._event(state, "trainer", "execute", "tier1", ComponentStatus.SUCCEEDED if tier1.status == "succeeded" else ComponentStatus.FAILED, "Isolated worktree test tier", {"receipt": receipts[-1]})
        if tier1.status != "succeeded":
            error = tier1.error or "tier1 failed"
            return {
                "tier_receipts": receipts, "error": error,
                "error_category": self.s.recovery.classify(error), "failure_stage": "execute",
            }
        config = workspace / "configs/experiments/bce_fm.yaml"
        tier2 = await self.s.funnel.tier2(workspace, Path(state["transform_dir"]), config, output / "tier2", 0)
        receipts.append(tier2.model_dump(mode="json"))
        self._event(state, "trainer", "execute", "tier2", ComponentStatus.SUCCEEDED if tier2.status == "succeeded" else ComponentStatus.FAILED, "Smoke-scale proxy run", {"receipt": receipts[-1]})
        if tier2.status != "succeeded":
            error = tier2.error or "tier2 failed"
            return {
                "tier_receipts": receipts, "error": error,
                "error_category": self.s.recovery.classify(error), "failure_stage": "execute",
            }
        if await self._behavior_unchanged_vs_baseline(
            state["session_id"], Path(state["transform_dir"]), output / "tier2", 0
        ):
            message = (
                "patch produced no measurable change in ranking behavior: proxy-scale "
                "within-user validation ordering is identical to the unpatched experiment "
                "baseline; the new capability was either not executed or cannot change "
                "GAUC/nDCG@5"
            )
            self._event(state, "phase_guard", "execute", "inert_patch", ComponentStatus.FAILED, message, {"tier2_output": str(output / "tier2")})
            return {
                "tier_receipts": receipts, "error": message,
                "error_category": "behavior_unchanged", "failure_stage": "execute",
            }
        tier3 = await self.s.funnel.tier3(workspace, Path(state["transform_dir"]), config, output / "tier3", 0)
        receipts.append(tier3.model_dump(mode="json"))
        self._event(state, "trainer", "execute", "tier3", ComponentStatus.SUCCEEDED if tier3.status == "succeeded" else ComponentStatus.FAILED, "Bounded proxy-scale run", {"receipt": receipts[-1]})
        if tier3.status != "succeeded":
            error = tier3.error or "tier3 failed"
            return {
                "tier_receipts": receipts, "error": error,
                "error_category": self.s.recovery.classify(error), "failure_stage": "execute",
            }
        tier4 = await self.s.funnel.tier4(workspace, Path(state["transform_dir"]), config, output / "tier4", 0)
        receipts.append(tier4.model_dump(mode="json"))
        self._event(state, "trainer", "execute", "tier4", ComponentStatus.SUCCEEDED if tier4.status == "succeeded" else ComponentStatus.FAILED, "Full-scale training run", {"receipt": receipts[-1]})
        if tier4.status != "succeeded":
            error = tier4.error or "tier4 failed"
            return {
                "tier_receipts": receipts, "error": error,
                "error_category": self.s.recovery.classify(error), "failure_stage": "execute",
            }
        return {"tier_receipts": receipts, "error": "", "error_category": "", "failure_stage": ""}

    @staticmethod
    def _same_within_user_ranking(
        users: np.ndarray,
        baseline_scores: np.ndarray,
        experiment_scores: np.ndarray,
    ) -> bool:
        if baseline_scores.shape != experiment_scores.shape or len(users) != len(baseline_scores):
            return False
        groups: dict[str, list[int]] = {}
        for index, user in enumerate(users.tolist()):
            groups.setdefault(str(user), []).append(index)
        for indices in groups.values():
            if len(indices) < 2:
                continue
            values = np.asarray(indices)
            baseline_order = values[np.argsort(-baseline_scores[values], kind="stable")]
            experiment_order = values[np.argsort(-experiment_scores[values], kind="stable")]
            if not np.array_equal(baseline_order, experiment_order):
                return False
        return True

    async def _behavior_unchanged_vs_baseline(
        self,
        session_id: str,
        transform_dir: Path,
        tier2_output: Path,
        seed: int,
    ) -> bool:
        key = (str(transform_dir), seed)
        if key not in self._reference_tier2_scores:
            reference_workspace, _ = self.s.workspace.create(f"baseline-reference-{new_id('ref')}", "HEAD")
            reference_output = (
                self.s.artifacts / "runs" / session_id / "_baseline_reference"
                / new_id("reference") / "tier2"
            )
            reference_receipt = await self.s.funnel.tier2(
                reference_workspace, transform_dir,
                reference_workspace / "configs/experiments/bce_fm.yaml", reference_output, seed,
            )
            reference_scores = reference_output / "model" / "valid_scores.npy"
            self._reference_tier2_scores[key] = (
                np.load(reference_scores)
                if reference_receipt.status == "succeeded" and reference_scores.is_file()
                else None
            )
        baseline_scores = self._reference_tier2_scores[key]
        if baseline_scores is None:
            return False
        experiment_path = tier2_output / "model" / "valid_scores.npy"
        if not experiment_path.is_file():
            raise RuntimeError(
                f"tier2 succeeded without required artifact {experiment_path}"
            )
        experiment_scores = np.load(experiment_path)
        with np.load(transform_dir / "valid.npz", allow_pickle=False) as data:
            users = data["users"][: len(experiment_scores)]
        return self._same_within_user_ranking(users, baseline_scores, experiment_scores)

    async def evaluate(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        tier4 = next(
            item for item in reversed(state.get("tier_receipts", []))
            if int(item["tier"]) == 4 and item["status"] == "succeeded"
        )
        output = Path(tier4["output_directory"]) / "model"
        scores = np.load(output / "valid_scores.npy")
        with np.load(Path(state["transform_dir"]) / "valid.npz", allow_pickle=False) as data:
            users, videos, labels = data["users"].tolist(), data["videos"].tolist(), data["y"].tolist()
        prediction = output / "predictions.csv"
        prediction_hash = self.s.evaluator.write_predictions(prediction, users, videos, scores)
        receipt = self.s.evaluator.score(
            run_id=state["run_id"], prediction_artifact_id=prediction_hash,
            config_hash=canonical_hash(state["experiment_contract"]), users=users, labels=labels, scores=scores,
        )
        duplicate_of_run_id = self.s.ledger.prior_run_for_prediction(
            state["session_id"],
            receipt.prediction_artifact_id,
            state["run_id"],
        )
        self.s.ledger.store_metric_receipt(
            state["session_id"], state["run_id"], receipt.model_dump(mode="json")
        )
        self._event(
            state,
            "evaluator",
            "validation",
            "metric",
            ComponentStatus.SUCCEEDED,
            "Official validation metrics recorded",
            {
                "metrics": {
                    "GAUC": receipt.gauc,
                    "nDCG@5": receipt.ndcg_at_5,
                    "primary": receipt.primary,
                },
                "receipt": receipt.model_dump(mode="json"),
                "prediction": str(prediction),
                "duplicate_of_run_id": duplicate_of_run_id,
            },
        )
        tier_receipts = state.get("tier_receipts", [])
        gpu_seconds = [item.get("gpu_seconds") for item in tier_receipts]
        measured_gpu = [value for value in gpu_seconds if value is not None]
        gpu_hours = round(sum(measured_gpu) / 3600, 6) if measured_gpu else None
        peak_gpu = [item.get("peak_gpu_memory_mb") for item in tier_receipts]
        measured_peak = [value for value in peak_gpu if value is not None]
        resource_totals = {
            "wall_seconds": sum(item.get("wall_seconds", 0.0) for item in tier_receipts),
            "peak_rss_mb": max((item.get("peak_rss_mb", 0.0) for item in tier_receipts), default=0.0),
            "peak_gpu_memory_mb": max(measured_peak) if measured_peak else None,
            "gpu_hours": gpu_hours,
            "gpu_hours_session_total": round(
                (state.get("gpu_seconds_used", 0.0) + sum(measured_gpu)) / 3600, 6
            ) if measured_gpu or state.get("gpu_seconds_used") else None,
            "bedrock_input_tokens": state.get("agent_input_tokens", 0),
            "bedrock_output_tokens": state.get("agent_output_tokens", 0),
            "retries": state.get("recovery_attempt", 0),
            "manual_interventions": self.s.ledger.manual_intervention_count(state["session_id"]),
        }
        self.s.ledger.store_resource_sample(
            state["session_id"], state["run_id"], resource_totals
        )
        self._event(state, "trainer", "resources", "usage", ComponentStatus.SUCCEEDED, "Resource usage recorded for this run", {"resources": resource_totals})
        values: dict[str, Any] = {
            "metric_receipt": receipt.model_dump(mode="json"),
            "gpu_seconds_used": state.get("gpu_seconds_used", 0.0) + sum(measured_gpu),
            "duplicate_prediction_run_id": duplicate_of_run_id,
        }
        if duplicate_of_run_id:
            values.update({
                "error": (
                    "Full-validation predictions are byte-identical to prior run "
                    f"{duplicate_of_run_id}; the proposed experiment did not produce distinct behavior"
                ),
                "error_category": "behavior_unchanged",
                "failure_stage": "execute",
            })
        else:
            values.update({
                "error": "",
                "error_category": "",
                "failure_stage": "",
                "experiment_count": state.get("experiment_count", 0) + 1,
            })
        return values

    async def decide(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        frontier = FrontierState.model_validate(state["frontier"])
        receipt = MetricReceipt.model_validate(state["metric_receipt"])
        best = MetricReceipt.model_validate(state["best_metric"])
        parent = MetricReceipt.model_validate(state["parent_metric"])
        duplicate_of_run_id = state.get("duplicate_prediction_run_id") or None
        updated, decision, converged = self.s.frontier.decide(
            frontier,
            receipt,
            state["run_id"],
            best,
            parent,
            duplicate_of_run_id=duplicate_of_run_id,
        )
        exhausted = self._budget_exhausted(state)
        budget_stop = bool(exhausted)
        stop = converged or budget_stop
        if stop:
            updated = self.s.frontier.budget_stop(updated)
        self.s.ledger.store_frontier(state["session_id"], updated)
        summary = (
            f"Experiment reject: predictions duplicate {duplicate_of_run_id}"
            if duplicate_of_run_id
            else f"Experiment {decision}"
        )
        self._event(
            state,
            "watchdog",
            "decision",
            "frontier",
            ComponentStatus.SUCCEEDED if stop else ComponentStatus.READY,
            summary,
            {
                "frontier": updated.model_dump(mode="json"),
                "decision": decision,
                "converged": converged,
                "budget_stop": budget_stop,
                "budget_reason": exhausted,
                "experiment_id": ExperimentContract.model_validate(
                    state["experiment_contract"]
                ).experiment_id,
                "duplicate_of_run_id": duplicate_of_run_id,
            },
        )
        values: dict[str, Any] = {
            "frontier": updated.model_dump(mode="json"),
            "stop": stop,
            "stop_reason": "convergence" if converged else ("budget" if budget_stop else ""),
        }
        if updated.validation_best == state["run_id"]:
            values.update({
                "best_metric": state["metric_receipt"],
                "parent_metric": state["metric_receipt"],
            })
        return values

    # A failure in these categories means the *contract* was sound and the
    # *patch* was wrong, so retrying the patch for the same contract is far
    # cheaper than discarding a good hypothesis and burning a fresh research
    # call on a new one -- which is what previously happened, causing the same
    # inert-patch mistake to repeat indefinitely.
    CODE_LEVEL_CATEGORIES = frozenset({"behavior_unchanged", "code_patch", "syntax_import_config"})
    ABANDON_CONTRACT_CATEGORIES = frozenset({"code_stage_timeout", "experiment_scope"})


    async def recover(self, state: WorkflowState) -> dict[str, Any]:
        await self._control_gate(state)
        attempt = state.get("recovery_attempt", 0) + 1
        # A Research/Code Agent call can fail before an ExperimentContract
        # exists (e.g. an Azure AI Foundry rate limit on the very first call
        # of an iteration); fall back to one bounded attempt rather than
        # crashing on the missing contract.
        contract = ExperimentContract.model_validate(state["experiment_contract"]) if state.get("experiment_contract") else None
        attempt_limit = contract.recovery_attempt_limit if contract else 1
        receipt = self.s.recovery.recover(
            state["run_id"], state["error"], attempt, attempt_limit,
            category=state.get("error_category") or None,
        )
        code_origin = state.get("failure_stage") in {"code", "execute"}
        retry_same_contract = (
            receipt.category not in self.ABANDON_CONTRACT_CATEGORIES
            and (code_origin or receipt.category in self.CODE_LEVEL_CATEGORIES)
        )
        retry_target = "code" if contract and retry_same_contract else "research"
        event_payload = {
            **receipt.model_dump(mode="json"),
            "retry_target": "research" if attempt > attempt_limit else retry_target,
            "experiment_id": contract.experiment_id if contract else None,
            "completed_experiments": state.get("experiment_count", 0),
            "experiment_attempts": state.get("experiment_attempt_count", 0),
        }
        self.s.ledger.store_recovery_receipt(
            state["session_id"], state["run_id"], receipt.model_dump(mode="json")
        )
        self._event(
            state, "recovery", "recovery", "recovery",
            ComponentStatus.FAILED if attempt > attempt_limit else ComponentStatus.READY,
            receipt.action, event_payload,
        )
        if attempt > attempt_limit or receipt.category == "metric_regression":
            frontier = FrontierState.model_validate(state["frontier"])
            frontier.failed.append(state["run_id"])
            stop_reason = self._budget_exhausted(state)
            stop = bool(stop_reason)
            if stop:
                frontier = self.s.frontier.budget_stop(frontier)
                self.s.ledger.store_frontier(state["session_id"], frontier)
                self._event(
                    state, "watchdog", "decision", "frontier", ComponentStatus.SUCCEEDED,
                    f"Stopping after exhausted recovery: {stop_reason}",
                    {
                        "frontier": frontier.model_dump(mode="json"),
                        "decision": "failed", "converged": False, "budget_stop": True,
                        "budget_reason": stop_reason,
                        "experiment_id": contract.experiment_id if contract else None,
                    },
                )
            return {
                "recovery_attempt": attempt, "error": "", "error_category": "",
                "failure_stage": "", "last_execution_error": "",
                "retry_target": "research", "frontier": frontier.model_dump(mode="json"),
                "stop": stop, "stop_reason": "budget" if stop else "",
            }
        # Code and execution failures stay on the same run ID and contract.
        # They consume recovery attempts and resource budgets, not completed
        # validation-experiment slots.
        return {
            "recovery_attempt": attempt, "error": "", "error_category": "",
            "last_execution_error": state.get("error", "") if retry_target == "code" else "",
            "recovery_action": receipt.action,
            "retry_target": retry_target,
        }

    def _route_baseline(self, state: WorkflowState) -> str:
        return "stop" if state.get("stop") else "research"

    def _route_research(self, state: WorkflowState) -> str:
        if state.get("stop"):
            return "stop"
        return "recover" if state.get("error") else "code"

    def _route_code(self, state: WorkflowState) -> str:
        return "recover" if state.get("error") else "execute"

    def _route_execute(self, state: WorkflowState) -> str:
        return "recover" if state.get("error") else "evaluate"

    def _route_evaluate(self, state: WorkflowState) -> str:
        return "recover" if state.get("error") else "decide"

    def _route_decide(self, state: WorkflowState) -> str:
        return "stop" if state.get("stop") else "research"

    def _route_recovery(self, state: WorkflowState) -> str:
        if state.get("stop"):
            return "stop"
        return "code" if state.get("retry_target") == "code" else "research"

    def _build(self, checkpointer=None):
        graph = StateGraph(WorkflowState)
        for name in ("prepare", "profile", "baseline", "research", "code", "execute", "evaluate", "decide", "recover"):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "prepare")
        graph.add_edge("prepare", "profile")
        graph.add_edge("profile", "baseline")
        graph.add_conditional_edges("baseline", self._route_baseline, {"research": "research", "stop": END})
        graph.add_conditional_edges("research", self._route_research, {"code": "code", "recover": "recover", "stop": END})
        graph.add_conditional_edges("code", self._route_code, {"execute": "execute", "recover": "recover"})
        graph.add_conditional_edges("execute", self._route_execute, {"recover": "recover", "evaluate": "evaluate"})
        graph.add_conditional_edges(
            "evaluate",
            self._route_evaluate,
            {"recover": "recover", "decide": "decide"},
        )
        graph.add_conditional_edges("decide", self._route_decide, {"research": "research", "stop": END})
        graph.add_conditional_edges("recover", self._route_recovery, {"research": "research", "code": "code", "stop": END})
        return graph.compile(checkpointer=checkpointer)

    async def run(self, session_id: str) -> WorkflowState:
        initial: WorkflowState = {
            "session_id": session_id, "run_id": "workflow", "status": "running",
            "agent_input_tokens": 0, "agent_output_tokens": 0,
            "experiment_count": 0, "experiment_attempt_count": 0,
            "recovery_attempt": 0, "stop": False, "started_at": time.time(),
        }
        self.s.ledger.set_session_status(session_id, ComponentStatus.RUNNING)
        checkpoint_path = self.s.ledger.database.with_name("langgraph.sqlite3")
        try:
            async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
                await saver.setup()
                durable_graph = self._build(checkpointer=saver)
                result = await durable_graph.ainvoke(
                    initial,
                    config={"configurable": {"thread_id": session_id}},
                )
            stop_reason = result.get("stop_reason")
            terminal_status = (
                ComponentStatus.BLOCKED
                if stop_reason == "baseline_gate"
                else ComponentStatus.FAILED
                if stop_reason == "baseline_failure"
                else ComponentStatus.SUCCEEDED
            )
            self.s.ledger.set_session_status(session_id, terminal_status)
            terminal_summary = (
                "Workflow blocked by the baseline integrity gate"
                if terminal_status == ComponentStatus.BLOCKED
                else "Workflow stopped because baseline execution or its safety checks failed"
                if terminal_status == ComponentStatus.FAILED
                else "Validation research loop stopped safely; final hidden-test packaging awaits explicit confirmation"
            )
            self._event(
                result, "orchestrator", "workflow", "completed", terminal_status,
                terminal_summary,
                {
                    "stop_reason": stop_reason or "",
                    "next_action": "package" if terminal_status == ComponentStatus.SUCCEEDED else None,
                },
            )
            return result
        except asyncio.CancelledError:
            self.s.ledger.set_session_status(session_id, ComponentStatus.FAILED)
            raise
        except Exception as error:
            self.s.ledger.set_session_status(session_id, ComponentStatus.FAILED)
            message = f"{type(error).__name__}: {error}"
            self._event(
                initial, "orchestrator", "workflow", "failed", ComponentStatus.FAILED,
                f"Workflow halted by an uncaught exception: {message}",
                {"error": message},
            )
            raise
        finally:
            try:
                await self.s.knowledge.close()
            except Exception:
                pass
