from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rigor_rs.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches, PatchProposal
from rigor_rs.integrity.gates import IntegrityViolation
from rigor_rs.orchestration.workspace import WorkspaceManager


def run(*args: str, cwd: Path) -> None:
    subprocess.run(list(args), cwd=cwd, check=True, capture_output=True)


def contract(allowed: list[str]) -> ExperimentContract:
    return ExperimentContract(
        experiment_id="E1", parent_run_id="B0", hypothesis="Pairwise loss improves within-user ranking quality",
        observed_evidence_ids=["paper"], primary_change="change loss", allowed_files=allowed,
        prohibited_files=["kuairand-starter-kit/evaluate.py"], predicted_gauc_direction="up",
        predicted_ndcg_at_5_direction="up", falsifiers=["validation regression"],
        outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
        comparator_run_id="B0", minimum_primary_improvement=0.002, guardrails=["official evaluator"],
        budget=ExperimentBudget(wall_seconds=60, gpu_hours=0, bedrock_input_tokens=1000, bedrock_output_tokens=1000),
        fallback_run_id="B0", recovery_attempt_limit=1,
    )


def test_patch_scope_and_git_apply_check(tmp_path: Path) -> None:
    repo = tmp_path / "repo"; repo.mkdir()
    run("git", "init", cwd=repo)
    (repo / "model.py").write_text("LOSS = 'bce'\n", encoding="utf-8")
    run("git", "add", ".", cwd=repo)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    manager = WorkspaceManager(repo, tmp_path / "worktrees")
    workspace, _ = manager.create("E1")
    proposal = PatchProposal(
        unified_diff="""diff --git a/model.py b/model.py\nindex c57762b..12805b9 100644\n--- a/model.py\n+++ b/model.py\n@@ -1 +1 @@\n-LOSS = 'bce'\n+LOSS = 'bpr'\n""",
        explanation="align loss", tests=[],
    )
    _, _, paths = manager.apply(workspace, contract(["model.py"]), proposal)
    assert paths == ["model.py"]
    assert "bpr" in (workspace / "model.py").read_text()
    with pytest.raises(IntegrityViolation):
        manager.validate_proposal(workspace, contract(["model.py"]), PatchProposal(
            unified_diff="""diff --git a/kuairand-starter-kit/evaluate.py b/kuairand-starter-kit/evaluate.py\n--- a/kuairand-starter-kit/evaluate.py\n+++ b/kuairand-starter-kit/evaluate.py\n@@ -1 +1 @@\n-old\n+new\n""",
            explanation="bad", tests=[],
        ))
    invalid = PatchProposal(
        unified_diff=(
            "diff --git a/model.py b/model.py\n"
            "--- a/model.py\n"
            "+++ b/model.py\n"
            "@@ -1 +1 @@\n"
            "-LOSS = 'missing'\n"
            "+LOSS = 'bpr'\n"
        ),
        explanation="invalid context",
        tests=[],
    )
    with pytest.raises(IntegrityViolation, match="patch failed git apply --check"):
        manager.apply(workspace, contract(["model.py"]), invalid)
    bare_hunk = PatchProposal(
        unified_diff=(
            "diff --git a/model.py b/model.py\n"
            "--- a/model.py\n"
            "+++ b/model.py\n"
            "@@\n"
            "-old\n"
            "+new\n"
        ),
        explanation="invalid hunk",
        tests=[],
    )
    with pytest.raises(IntegrityViolation, match="invalid unified-diff hunk header"):
        manager.validate_proposal(workspace, contract(["model.py"]), bare_hunk)
