from __future__ import annotations

import asyncio
import json
from pathlib import Path
import time
from typing import Annotated, Any

import yaml
import typer
import uvicorn

from rigor_rs.agents.azure_foundry import AzureAgentFactory
from rigor_rs.api.server import WorkflowHost, create_app
from rigor_rs.contract.challenge import load_challenge_contract, sha256_file
from rigor_rs.contract.models import ComponentStatus, DataArtifact, ProfileConfig, SplitTaint, TransformSpec
from rigor_rs.data.profiler import PreprocessorService, ProfilerService
from rigor_rs.evaluation.official import OfficialEvaluator
from rigor_rs.integrity.gates import evaluator_metamorphic_checks
from rigor_rs.knowledge.config import load_budget_config, repository_root
from rigor_rs.knowledge.runtime import KnowledgeRuntime
from rigor_rs.ledger.workflow import WorkflowLedger, canonical_hash, new_id
from rigor_rs.orchestration.frontier import FrontierManager
from rigor_rs.orchestration.graph import AutonomousResearchWorkflow, WorkflowServices
from rigor_rs.orchestration.workspace import WorkspaceManager
from rigor_rs.recovery.controller import RecoveryController
from rigor_rs.reporting.finalizer import SubmissionFinalizer
from rigor_rs.training.baseline import BaselineReproducer
from rigor_rs.training.execution import ExecutionFunnel

app = typer.Typer(help="Validate and run the autonomous KuaiRand research workflow.", no_args_is_help=True)


def emit(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def _data_artifact(contract) -> DataArtifact:
    root = repository_root()
    files = [
        contract.dataset_dir / "log_standard_4_08_to_4_21_pure.csv",
        contract.dataset_dir / "log_standard_4_22_to_5_08_pure.csv",
    ]
    return DataArtifact(
        artifact_id=new_id("data"), path=contract.dataset_dir,
        taints={SplitTaint.TRAIN_FEATURES, SplitTaint.TRAIN_LABELS, SplitTaint.VALIDATION_FEATURES},
        row_count=0, schema_fingerprint="kuairand-dev-logs",
        source_hash=canonical_hash({str(path): sha256_file(path) for path in files}),
        code_hash=sha256_file(root / "src/rigor_rs/data/profiler.py"), creation_receipt_id=new_id("receipt"),
    )


def build_workflow(challenge_path: str, budget_path: str, ledger: WorkflowLedger | None = None) -> tuple[AutonomousResearchWorkflow, WorkflowLedger, SubmissionFinalizer]:
    root = repository_root()
    contract = load_challenge_contract(challenge_path)
    budget = load_budget_config(root / budget_path if not Path(budget_path).is_absolute() else Path(budget_path))
    ledger = ledger or WorkflowLedger(root / "state/rigor.sqlite3")
    artifacts = root / "artifacts"
    agents = AzureAgentFactory()
    knowledge = KnowledgeRuntime()
    services = WorkflowServices(
        contract=contract, ledger=ledger,
        profiler=ProfilerService(contract, artifacts), preprocessor=PreprocessorService(contract, artifacts),
        baseline=BaselineReproducer(contract, root / "configs/baseline/official_fm.yaml", artifacts),
        agents=agents, knowledge=knowledge,
        workspace=WorkspaceManager(root, root / "state/worktrees", agents.config.context_limits.maximum_patch_characters, agents.config.context_limits.maximum_reference_code_characters),
        funnel=ExecutionFunnel(contract, artifacts, int(budget.limits["per_run_timeout_seconds"]), budget.proxy_tier),
        evaluator=OfficialEvaluator(contract), frontier=FrontierManager(contract.convergence_epsilon, contract.convergence_patience),
        recovery=RecoveryController(), repository=root, artifacts=artifacts,
        maximum_experiments=int(budget.limits["maximum_experiments"]),
        bedrock_input_limit=int(budget.limits["bedrock_input_tokens"]),
        bedrock_output_limit=int(budget.limits["bedrock_output_tokens"]),
        total_wall_seconds=int(budget.limits["total_wall_seconds"]),
    )
    return AutonomousResearchWorkflow(services), ledger, SubmissionFinalizer(contract, ledger, artifacts)


@app.command("validate")
def validate(
    challenge: Annotated[str, typer.Option("--challenge")] = "configs/challenge/kuairand_pure.yaml",
    budget: Annotated[str, typer.Option("--budget")] = "configs/budgets/competition.yaml",
) -> None:
    root = repository_root()
    contract = load_challenge_contract(challenge)
    budget_document = load_budget_config(root / budget if not Path(budget).is_absolute() else Path(budget))
    checks = evaluator_metamorphic_checks(contract)
    if not all(checks.values()):
        emit({"status": "failed", "metamorphic_checks": checks})
        raise typer.Exit(1)
    emit({
        "status": "valid", "challenge": contract.public_summary(),
        "budget_limits": budget_document.limits, "proxy_limits": budget_document.proxy_tier,
        "metamorphic_checks": checks, "test_labels_accessed": False,
    })


@app.command("profile")
def profile(
    challenge: Annotated[str, typer.Option("--challenge")] = "configs/challenge/kuairand_pure.yaml",
) -> None:
    root = repository_root(); contract = load_challenge_contract(challenge)
    artifact = _data_artifact(contract)
    profiler = ProfilerService(contract, root / "artifacts")
    preprocessor = PreprocessorService(contract, root / "artifacts")
    receipt = profiler.profile(artifact, ProfileConfig())
    transform = preprocessor.fit_apply(artifact, TransformSpec())
    emit({"status": "completed", "profile": receipt.model_dump(mode="json"), "transform": transform.model_dump(mode="json")})


@app.command("baseline-progress")
def baseline_progress(
    follow: Annotated[bool, typer.Option("--follow")] = False,
    interval: Annotated[float, typer.Option("--interval")] = 2.0,
) -> None:
    """Print per-seed FM epochs from the newest baseline run."""
    baseline_root = repository_root() / "artifacts/baseline"
    last_rendered = ""
    while True:
        runs = (
            sorted(
                (path for path in baseline_root.glob("B0-*") if path.is_dir()),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
            if baseline_root.is_dir()
            else []
        )
        if not runs:
            document: dict[str, Any] = {"status": "waiting", "detail": "no baseline run found"}
            completed = False
        else:
            latest = runs[0]
            progress = []
            for path in sorted(latest.glob("progress_seed_*.json")):
                try:
                    progress.append(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    continue
            completed = (latest / "baseline_receipt.json").is_file()
            document = {
                "status": "completed" if completed else "running",
                "run_directory": str(latest),
                "seeds": progress,
            }
        rendered = json.dumps(document, ensure_ascii=False, sort_keys=True, default=str)
        if rendered != last_rendered:
            typer.echo(rendered)
            last_rendered = rendered
        if completed or not follow:
            return
        time.sleep(max(0.25, interval))


@app.command("reproduce-baseline")
def reproduce_baseline(
    challenge: Annotated[str, typer.Option("--challenge")] = "configs/challenge/kuairand_pure.yaml",
    seeds: Annotated[str | None, typer.Option("--seeds", help="Comma-separated; omit for configured 0-4")]=None,
) -> None:
    root = repository_root(); contract = load_challenge_contract(challenge); artifact = _data_artifact(contract)
    transform = PreprocessorService(contract, root / "artifacts").fit_apply(artifact, TransformSpec())
    reproducer = BaselineReproducer(contract, root / "configs/baseline/official_fm.yaml", root / "artifacts")
    result = reproducer.reproduce(transform.receipt.path.parent, seeds=[int(value) for value in seeds.split(",")] if seeds else None)
    result["harness"] = {name: value.model_dump(mode="json") for name, value in reproducer.harness_checks(transform.receipt.path.parent).items()}
    result["label_shuffle"] = reproducer.label_shuffle_control(transform.receipt.path.parent)
    emit(result)
    if result["status"] != "succeeded" or not result["label_shuffle"]["passed"]:
        raise typer.Exit(1)


@app.command("run")
def run(
    challenge: Annotated[str, typer.Option("--challenge")] = "configs/challenge/kuairand_pure.yaml",
    budget: Annotated[str, typer.Option("--budget")] = "configs/budgets/competition.yaml",
) -> None:
    workflow, ledger, _ = build_workflow(challenge, budget)
    session_id = ledger.create_session()
    result = asyncio.run(workflow.run(session_id))
    emit({"session_id": session_id, "status": "completed", "state": result, "snapshot": ledger.snapshot(session_id).model_dump(mode="json"), "event_chain_valid": ledger.verify_chain(session_id)})


def _control(action: str, session_id: str) -> None:
    ledger = WorkflowLedger(repository_root() / "state/rigor.sqlite3")
    snapshot = ledger.snapshot(session_id)
    accepted, reason = ledger.control(session_id, action, snapshot.latest_sequence)
    if not accepted:
        emit({"accepted": False, "reason": reason}); raise typer.Exit(1)
    ledger.append_event(
        session_id=session_id, run_id=snapshot.current_run_id or "workflow", component_id="watchdog",
        execution_id=f"cli-{action}", stage="control", event_type=f"control_{action}",
        status=ComponentStatus.PAUSED if action == "pause" else (ComponentStatus.FAILED if action == "cancel" else ComponentStatus.RUNNING),
        plain_summary=f"CLI {action} accepted",
    )
    emit({"accepted": True, "session_id": session_id, "action": action})


@app.command("pause")
def pause(session_id: str): _control("pause", session_id)
@app.command("resume")
def resume(session_id: str): _control("resume", session_id)
@app.command("cancel")
def cancel(session_id: str): _control("cancel", session_id)


@app.command("replay")
def replay(session_id: str) -> None:
    ledger = WorkflowLedger(repository_root() / "state/rigor.sqlite3")
    emit({"mode": "replay", "events": [event.model_dump(mode="json") for event in ledger.events(session_id)], "snapshot": ledger.snapshot(session_id).model_dump(mode="json")})


@app.command("report")
def report(session_id: str) -> None:
    ledger = WorkflowLedger(repository_root() / "state/rigor.sqlite3")
    emit({"session_id": session_id, "snapshot": ledger.snapshot(session_id).model_dump(mode="json"), "event_chain_valid": ledger.verify_chain(session_id), "events": len(ledger.events(session_id))})


@app.command("package-submission")
def package_submission(
    session_id: str,
    confirmation: Annotated[str, typer.Option("--confirmation")],
    challenge: Annotated[str, typer.Option("--challenge")] = "configs/challenge/kuairand_pure.yaml",
) -> None:
    if confirmation != session_id:
        raise typer.BadParameter("confirmation must exactly match session_id")
    contract = load_challenge_contract(challenge)
    ledger = WorkflowLedger(repository_root() / "state/rigor.sqlite3")
    emit(SubmissionFinalizer(contract, ledger, repository_root() / "artifacts").package(session_id))


@app.command("serve-ui")
def serve_ui(
    challenge: Annotated[str, typer.Option("--challenge")] = "configs/challenge/kuairand_pure.yaml",
    budget: Annotated[str, typer.Option("--budget")] = "configs/budgets/competition.yaml",
) -> None:
    root = repository_root(); contract = load_challenge_contract(challenge)
    ledger = WorkflowLedger(root / "state/rigor.sqlite3")
    finalizer = SubmissionFinalizer(contract, ledger, root / "artifacts")
    def factory(challenge_value: str, budget_value: str):
        return build_workflow(challenge_value, budget_value, ledger)[0]
    host = WorkflowHost(ledger, factory, finalizer.package)
    ui_config = yaml.safe_load((root / "configs/ui/observer.yaml").read_text(encoding="utf-8"))
    app_instance = create_app(host, root / "ui/dist")
    uvicorn.run(app_instance, host=ui_config["server"]["host"], port=int(ui_config["server"]["port"]))
