from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import psutil
import torch
import pytest

from flowstate.contract.challenge import load_challenge_contract
from flowstate.recovery.controller import RecoveryController
from flowstate.training.execution import ExecutionFunnel
from flowstate.training.experiment import predict, resolve_device


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
async def test_run_cancellation_stops_the_active_process(tmp_path: Path) -> None:
    funnel = object.__new__(ExecutionFunnel)
    marker = tmp_path / "process-survived.txt"
    run = asyncio.create_task(
        funnel._run(
            tier=1,
            command=[
                sys.executable,
                "-c",
                f"import pathlib,time; time.sleep(2); pathlib.Path({str(marker)!r}).write_text('alive')",
            ],
            cwd=tmp_path,
            output=tmp_path / "cancelled-tier",
            comparable=False,
            timeout=30,
        )
    )
    await asyncio.sleep(0.2)

    run.cancel()

    with pytest.raises(asyncio.CancelledError):
        await run
    await asyncio.sleep(2)
    assert not marker.exists()

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


def test_auto_device_uses_cpu_without_supported_gpu(monkeypatch) -> None:
    monkeypatch.setattr("torch.cuda.is_available", lambda: False)
    monkeypatch.setattr("torch.backends.mps.is_available", lambda: False)

    assert str(resolve_device("auto")) == "cpu"


def test_auto_device_uses_apple_mps_when_available(monkeypatch) -> None:
    monkeypatch.setattr("torch.cuda.is_available", lambda: False)
    monkeypatch.setattr("torch.backends.mps.is_available", lambda: True)

    assert str(resolve_device("auto")) == "mps"

def test_checkpoint_prediction_uses_training_model_contract(tmp_path: Path) -> None:
    from flowstate.models.experimental import FactorizationMachine

    model = FactorizationMachine(20, 4)
    checkpoint = tmp_path / "checkpoint.pt"
    torch.save(
        {
            "state_dict": model.state_dict(),
            "dimension": 20,
            "config": {"model": {"factors": 4}, "device": "cpu"},
        },
        checkpoint,
    )
    features = np.asarray([[1, 2, 3, 4, 5], [2, 3, 4, 5, 6]], dtype=np.int32)
    data = tmp_path / "test_features.npz"
    np.savez_compressed(data, X=features)
    output = tmp_path / "scores.npy"

    receipt = predict(checkpoint, data, output)

    with torch.no_grad():
        expected = model(torch.as_tensor(features, dtype=torch.long)).numpy()
    assert receipt["rows"] == 2
    assert receipt["device"] == "cpu"
    assert receipt["device_name"] == "CPU"
    np.testing.assert_allclose(np.load(output), expected)


def test_gpu_seconds_stay_null_when_nvml_cannot_observe_the_device() -> None:
    # GPU-hours must be measured, never invented. When NVML is unavailable the
    # value stays null so the UI reads "not measured" rather than "0 hours".
    from flowstate.training.execution import ResourceMonitor

    monitor = object.__new__(ResourceMonitor)
    monitor.process = psutil.Process()
    monitor.peak_rss = 0
    monitor.peak_gpu = None
    monitor.gpu_seconds = None
    monitor._last_sample = None
    monitor.gpu_device_names = set()
    monitor._nvml_ready = False

    monitor.sample()
    monitor.sample()

    assert monitor.gpu_seconds is None
    assert monitor.peak_gpu is None
    assert monitor.peak_rss > 0


def test_gpu_seconds_accumulate_only_while_the_process_holds_the_device(monkeypatch) -> None:
    from types import SimpleNamespace

    import flowstate.training.execution as execution

    monitor = object.__new__(execution.ResourceMonitor)
    monitor.process = psutil.Process()
    monitor.peak_rss = 0
    monitor.peak_gpu = None
    monitor.gpu_seconds = 0.0
    monitor._last_sample = None
    monitor.gpu_device_names = set()
    monitor._nvml_ready = True

    active = {"value": False}
    clock = {"value": 100.0}
    monkeypatch.setattr(execution.time, "monotonic", lambda: clock["value"])
    monkeypatch.setattr(
        execution,
        "pynvml",
        SimpleNamespace(
            nvmlDeviceGetCount=lambda: 1,
            nvmlDeviceGetName=lambda _handle: b"NVIDIA Test GPU",
            nvmlDeviceGetHandleByIndex=lambda _index: object(),
            # usedGpuMemory=None reproduces Windows/WDDM, where per-process
            # memory accounting is unavailable but presence in the compute list
            # still proves the device was in use.
            nvmlDeviceGetComputeRunningProcesses=lambda _handle: (
                [SimpleNamespace(pid=monitor.process.pid, usedGpuMemory=None)] if active["value"] else []
            ),
        ),
    )

    monitor.sample()
    clock["value"] += 5.0
    monitor.sample()
    assert monitor.gpu_seconds == 0.0

    active["value"] = True
    clock["value"] += 4.0
    monitor.sample()
    assert monitor.gpu_seconds == 4.0
    assert monitor.peak_gpu is None
    assert monitor.gpu_device_names == {"NVIDIA Test GPU"}

    active["value"] = False
    clock["value"] += 7.0
    monitor.sample()
    assert monitor.gpu_seconds == 4.0


def test_full_scale_validation_rejects_truncated_fixed_splits(tmp_path: Path) -> None:
    funnel = object.__new__(ExecutionFunnel)
    transform = tmp_path / "transform"
    transform.mkdir()
    np.savez_compressed(transform / "train.npz", X=np.zeros((3, 2), dtype=np.int32))
    np.savez_compressed(transform / "valid.npz", X=np.zeros((4, 2), dtype=np.int32))
    output = tmp_path / "tier4"
    model = output / "model"
    model.mkdir(parents=True)
    (model / "train_receipt.json").write_text(
        '{"rows_train":3,"rows_valid":2}',
        encoding="utf-8",
    )
    np.save(model / "valid_scores.npy", np.asarray([0.1, 0.2], dtype=np.float32))
    receipt = funnel._preflight_failure(4, output, "placeholder").model_copy(
        update={"status": "succeeded", "error": None, "return_code": 0}
    )

    validated = funnel._validate_full_scale_rows(receipt, transform)

    assert validated.status == "failed"
    assert "full-scale validation row count mismatch" in validated.error
    assert "expected=4" in validated.error


def test_cuda_request_is_cross_checked_with_nvml_device(tmp_path: Path) -> None:
    funnel = object.__new__(ExecutionFunnel)
    output = tmp_path / "tier4"
    model = output / "model"
    model.mkdir(parents=True)
    (model / "train_receipt.json").write_text(
        '{"device":"cuda:0","device_name":"NVIDIA GeForce RTX 5060 Laptop GPU"}',
        encoding="utf-8",
    )
    config = tmp_path / "candidate.yaml"
    config.write_text("device: cuda\n", encoding="utf-8")
    receipt = funnel._preflight_failure(4, output, "placeholder").model_copy(
        update={
            "status": "succeeded",
            "error": None,
            "return_code": 0,
            "gpu_seconds": 3.0,
            "gpu_device_names": ["NVIDIA GeForce RTX 5060 Laptop GPU"],
        }
    )

    assert funnel._validate_requested_device(receipt, config) is receipt

    mismatched = receipt.model_copy(update={"gpu_device_names": ["Different NVIDIA GPU"]})
    rejected = funnel._validate_requested_device(mismatched, config)
    assert rejected.status == "failed"
    assert "NVML observed" in rejected.error
