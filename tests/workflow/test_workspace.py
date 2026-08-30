from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rigor_rs.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches, PatchProposal
from rigor_rs.integrity.gates import IntegrityViolation
from rigor_rs.orchestration.workspace import WorkspaceManager


def run(*args: str, cwd: Path) -> None:
    subprocess.run(list(args), cwd=cwd, check=True, capture_output=True)


def run_output(*args: str, cwd: Path) -> str:
    return subprocess.run(
        list(args), cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout


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
    workspace, _ = manager.create("E1", required_paths=["model.py"])
    proposal = PatchProposal(
        unified_diff="""diff --git a/model.py b/model.py\nindex c57762b..12805b9 100644\n--- a/model.py\n+++ b/model.py\n@@ -1 +1 @@\n-LOSS = 'bce'\n+LOSS = 'bpr'\n""",
        explanation="align loss", tests=[],
    )
    patch, _, paths = manager.apply(workspace, contract(["model.py"]), proposal)
    assert paths == ["model.py"]
    assert "bpr" in (workspace / "model.py").read_text()
    assert patch == tmp_path / "patches" / "E1" / "diff.patch"
    assert patch.is_file()
    assert not (workspace / "diff.patch").exists()
    (workspace / "unrelated.txt").write_text("must not be staged\n", encoding="utf-8")
    commit_hash = manager.commit(workspace, "E1", paths)
    assert len(commit_hash) == 40
    assert run_output("git", "show", "--format=", "--name-only", "HEAD", cwd=workspace).strip() == "model.py"
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


def test_apply_rejects_and_reverts_syntactically_invalid_python(tmp_path: Path) -> None:
    # Reproduced live: the agent returns file content inside a JSON string, so a
    # single-escaped "\n" decodes into a real newline inside a string literal.
    # The patch applies cleanly but the resulting Python does not compile. This
    # must be caught here (so the Code Agent gets a repair round-trip) and the
    # worktree restored, rather than surfacing later as an uncaught crash.
    repo = tmp_path / "repo2"; repo.mkdir()
    run("git", "init", cwd=repo)
    (repo / "model.py").write_text("VALUE = 'ok'\n", encoding="utf-8")
    run("git", "add", ".", cwd=repo)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    manager = WorkspaceManager(repo, tmp_path / "worktrees2")
    workspace, _ = manager.create("E2", required_paths=["model.py"])

    broken = PatchProposal(
        unified_diff=(
            "diff --git a/model.py b/model.py\n"
            "--- a/model.py\n"
            "+++ b/model.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 'ok'\n"
            "+VALUE = 'unterminated\n"
        ),
        explanation="mangled escape",
        tests=[],
    )

    with pytest.raises(IntegrityViolation, match="is not valid Python"):
        manager.apply(workspace, contract(["model.py"]), broken)
    # The worktree must be restored so the Code Agent's repaired patch, which
    # is generated against the original content, still applies.
    assert (workspace / "model.py").read_text(encoding="utf-8") == "VALUE = 'ok'\n"


def test_create_checks_out_only_runtime_and_contract_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo3"
    repo.mkdir()
    run("git", "init", cwd=repo)
    files = {
        "src/rigor_rs/runtime.py": "VALUE = 1\n",
        "configs/experiments/bce_fm.yaml": "training: {}\n",
        "kuairand-starter-kit/evaluate.py": "def evaluate(*args): return {}\n",
        "tests/workflow/test_experiment.py": "def test_contract(): pass\n",
        "tests/workflow/test_unrelated.py": "def test_unrelated(): pass\n",
        ".agents/skills.md": "not needed\n",
        "docs/architecture.md": "not needed\n",
        "ui/package.json": "{}\n",
        "pyproject.toml": "[project]\nname = 'fixture'\nversion = '0.0.0'\n",
    }
    for relative, content in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    run("git", "add", ".", cwd=repo)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "commit", "-m", "init"],
        cwd=repo, check=True, capture_output=True,
    )

    manager = WorkspaceManager(repo, tmp_path / "worktrees3")
    workspace, _ = manager.create(
        "E3",
        required_paths=["tests/workflow/test_experiment.py"],
    )

    assert (workspace / ".git").is_file()
    assert (workspace / "src/rigor_rs/runtime.py").is_file()
    assert (workspace / "configs/experiments/bce_fm.yaml").is_file()
    assert (workspace / "kuairand-starter-kit/evaluate.py").is_file()
    assert (workspace / "tests/workflow/test_experiment.py").is_file()
    assert (workspace / "pyproject.toml").is_file()
    assert not (workspace / "tests/workflow/test_unrelated.py").exists()
    assert not (workspace / ".agents").exists()
    assert not (workspace / "docs").exists()
    assert not (workspace / "ui").exists()
