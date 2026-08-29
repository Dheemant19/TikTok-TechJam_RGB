from __future__ import annotations

import sys
from pathlib import Path

import pytest

from rigor_rs.contract.challenge import load_challenge_contract
from rigor_rs.recovery.controller import RecoveryController
from rigor_rs.training.execution import ExecutionFunnel
from rigor_rs.training.experiment import resolve_device


def test_pytest_targets_normalize_commands_and_ignore_missing_paths(tmp_path: Path) -> None:
    workflow_tests = tmp_path / "tests/workflow"
    workflow_tests.mkdir(parents=True)
    (workflow_tests / "test_real.py").write_text("def test_real(): pass\n", encoding="utf-8")

    assert ExecutionFunnel._pytest_targets(
        tmp_path,
        ["python -m pytest tests/workflow/test_real.py"],
    ) == ["tests/workflow/test_real.py"]
    assert ExecutionFunnel._pytest_targets(
        tmp_path,
        ["tests/workflow/test_real.py::test_real"],
    ) == ["tests/workflow/test_real.py::test_real"]
    assert ExecutionFunnel._pytest_targets(
        tmp_path,
        ["python -m pytest tests/workflow/test_missing.py", "--collect-only; rm -rf ."],
    ) == []


def test_pytest_targets_falls_back_to_experiment_test_file_only(tmp_path: Path) -> None:
    workflow_tests = tmp_path / "tests/workflow"
    workflow_tests.mkdir(parents=True)
    (workflow_tests / "test_experiment.py").write_text("def test_x(): pass\n", encoding="utf-8")
    (workflow_tests / "test_unrelated.py").write_text("def test_y(): pass\n", encoding="utf-8")

    assert ExecutionFunnel._pytest_targets(tmp_path, []) == ["tests/workflow/test_experiment.py"]

    (workflow_tests / "test_experiment.py").unlink()
    assert ExecutionFunnel._pytest_targets(tmp_path, []) == []


@pytest.mark.asyncio
async def test_run_captures_stdout_only_failures_in_error_field(tmp_path: Path) -> None:
    funnel = object.__new__(ExecutionFunnel)
    receipt = await funnel._run(
        tier=1,
        # pytest-style collection errors print to stdout, not stderr; the
        # error field must not silently end up empty on this common failure.
        command=[sys.executable, "-c", "print('ERROR collecting test'); raise SystemExit(2)"],
        cwd=tmp_path,
        output=tmp_path / "tier1",
        comparable=False,
        timeout=30,
    )

    assert receipt.status == "failed"
    assert receipt.error
    assert "ERROR collecting test" in receipt.error


@pytest.mark.asyncio
async def test_tier1_does_not_run_unrelated_full_suite_when_no_scoped_test_exists(tmp_path: Path) -> None:
    # Reproduces the reported regression: an experiment legitimately changes an
    # allowed_files model (e.g. FactorizationMachine.forward's return shape) and
    # provides no targeted test. Tier1 must not fall back to the full, unrelated
    # tests/workflow suite (which would fail on interface assumptions elsewhere);
    # it must fall back to compileall on the touched files only.
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "tests/workflow").mkdir(parents=True)
    touched = workspace / "src" / "changed_model.py"
    touched.write_text("def forward():\n    return 1, 2\n", encoding="utf-8")
    (workspace / "tests/workflow/test_unrelated_interface.py").write_text(
        "def test_would_fail_on_new_interface():\n    assert False\n", encoding="utf-8"
    )

    funnel = ExecutionFunnel(load_challenge_contract(), tmp_path / "artifacts", 60, {})
    receipt = await funnel.tier1(
        workspace, ["src/changed_model.py"], [], tmp_path / "tier1-output"
    )

    assert receipt.status == "succeeded"
    assert "compileall" in receipt.command


@pytest.mark.asyncio
async def test_tier1_returns_failed_receipt_for_syntax_error_instead_of_raising(tmp_path: Path) -> None:
    # A SyntaxError in agent-generated code is a routine, expected failure. It
    # previously escaped execute() as a bare raise and killed the entire run
    # with no ledger event and no recovery; it must be a failed receipt.
    from types import SimpleNamespace

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "broken.py").write_text("VALUE = 'unterminated\n", encoding="utf-8")

    funnel = object.__new__(ExecutionFunnel)
    funnel.timeout_seconds = 60
    funnel.validator = SimpleNamespace(verify_official_files=lambda: None)

    receipt = await funnel.tier1(workspace, ["broken.py"], [], tmp_path / "tier1")

    assert receipt.status == "failed"
    assert "SyntaxError" in receipt.error
    assert "broken.py" in receipt.error


def test_successful_training_process_requires_complete_artifact_set(tmp_path: Path) -> None:
    funnel = object.__new__(ExecutionFunnel)
    output = tmp_path / "tier2"
    receipt = funnel._preflight_failure(2, output, "placeholder").model_copy(
        update={"status": "succeeded", "error": None, "return_code": 0}
    )

    validated = funnel._validate_training_artifacts(receipt)

    assert validated.status == "failed"
    assert "exited with code 0" in validated.error
    assert RecoveryController.classify(validated.error) == "code_patch"
    assert "model/valid_scores.npy" in validated.error
    assert "main entrypoint" in validated.error


def test_complete_training_artifacts_preserve_success_receipt(tmp_path: Path) -> None:
    funnel = object.__new__(ExecutionFunnel)
    output = tmp_path / "tier2"
    receipt = funnel._preflight_failure(2, output, "placeholder").model_copy(
        update={"status": "succeeded", "error": None, "return_code": 0}
    )
    for relative in funnel._REQUIRED_TRAINING_ARTIFACTS:
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"artifact")

    assert funnel._validate_training_artifacts(receipt) is receipt


def test_cuda_device_request_fails_loudly_instead_of_falling_back(monkeypatch) -> None:
    monkeypatch.setattr("torch.cuda.is_available", lambda: False)

    with pytest.raises(RuntimeError, match="requires CUDA"):
        resolve_device("cuda")


def test_cuda_device_request_resolves_unspecified_index(monkeypatch) -> None:
    monkeypatch.setattr("torch.cuda.is_available", lambda: True)
    monkeypatch.setattr("torch.cuda.current_device", lambda: 0)
    monkeypatch.setattr("torch.cuda.device_count", lambda: 1)

    assert str(resolve_device("cuda")) == "cuda:0"
