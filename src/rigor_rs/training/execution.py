from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import os
import signal
import re
import sys
import time
from pathlib import Path
from typing import Any, Literal

import psutil
from pydantic import BaseModel, ConfigDict, Field

from rigor_rs.contract.challenge import ChallengeContract
from rigor_rs.integrity.gates import PhaseBoundaryValidator
from rigor_rs.ledger.workflow import canonical_hash, new_id

try:
    import pynvml
except Exception:
    pynvml = None


class TierReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt_id: str
    tier: Literal[1, 2, 3, 4]
    status: Literal["succeeded", "failed", "rejected", "timeout"]
    comparable: bool
    command: list[str]
    return_code: int | None
    wall_seconds: float
    peak_rss_mb: float
    peak_gpu_memory_mb: float | None
    gpu_seconds: float | None = None
    stdout_path: Path
    stderr_path: Path
    output_directory: Path
    error: str | None = None
    receipt_hash: str


class ResourceMonitor:
    """Samples the process tree; GPU figures are measured, never estimated."""

    def __init__(self, pid: int) -> None:
        self.process = psutil.Process(pid)
        self.peak_rss = 0
        self.peak_gpu: float | None = None
        # Device-active seconds: wall time during which this process tree held a
        # CUDA compute context. None means NVML could not observe the device at
        # all, which must stay null rather than be reported as zero usage.
        self.gpu_seconds: float | None = None
        self._last_sample: float | None = None
        self._nvml_ready = False
        if pynvml:
            try:
                pynvml.nvmlInit()
                self._nvml_ready = True
                self.gpu_seconds = 0.0
            except Exception:
                pass

    def sample(self) -> None:
        now = time.monotonic()
        elapsed = 0.0 if self._last_sample is None else max(0.0, now - self._last_sample)
        self._last_sample = now
        try:
            processes = [self.process, *self.process.children(recursive=True)]
            self.peak_rss = max(self.peak_rss, sum(item.memory_info().rss for item in processes if item.is_running()))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        if not self._nvml_ready:
            return
        # NVML reports usedGpuMemory as None whenever per-process accounting is
        # unavailable (routine on Windows/WDDM). Summing that None previously
        # raised TypeError out of the sampler's finally block and failed every
        # training tier with "unsupported operand type(s) for +=". Presence in
        # the compute-process list is a separate, always-available signal and is
        # what device-active time is measured from.
        try:
            pids = {process.pid for process in processes}
            total = 0
            memory_measured = False
            device_active = False
            for index in range(pynvml.nvmlDeviceGetCount()):
                handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                for item in pynvml.nvmlDeviceGetComputeRunningProcesses(handle):
                    if item.pid not in pids:
                        continue
                    device_active = True
                    if item.usedGpuMemory is not None:
                        total += int(item.usedGpuMemory)
                        memory_measured = True
            if memory_measured:
                self.peak_gpu = max(self.peak_gpu or 0.0, total / 1024 / 1024)
            if device_active and self.gpu_seconds is not None:
                self.gpu_seconds += elapsed
        except Exception:
            # Telemetry must never fail a real training run; an unavailable
            # measurement stays null rather than becoming an invented number.
            self._nvml_ready = False

    def close(self) -> None:
        if self._nvml_ready:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass


class ExecutionFunnel:
    def __init__(self, contract: ChallengeContract, artifact_root: Path, timeout_seconds: int, proxy_config: dict[str, Any]) -> None:
        self.contract = contract
        self.artifact_root = artifact_root
        self.timeout_seconds = timeout_seconds
        self.proxy_config = proxy_config
        self.validator = PhaseBoundaryValidator(contract)
    _REQUIRED_TRAINING_ARTIFACTS = (
        "model/checkpoint.pt",
        "model/valid_scores.npy",
        "model/train_receipt.json",
    )

    @staticmethod
    def _rehash_receipt(document: dict[str, Any]) -> TierReceipt:
        return TierReceipt(
            **document,
            receipt_hash=canonical_hash({key: str(value) for key, value in document.items()}),
        )

    def _validate_training_artifacts(self, receipt: TierReceipt) -> TierReceipt:
        if receipt.status != "succeeded":
            return receipt
        missing = [
            relative
            for relative in self._REQUIRED_TRAINING_ARTIFACTS
            if not (receipt.output_directory / relative).is_file()
        ]
        if not missing:
            return receipt
        message = (
            "training process exited with code 0 but did not produce required artifacts: "
            + ", ".join(missing)
            + ". The training module may have been truncated or its main entrypoint may not have run."
        )
        with receipt.stderr_path.open("a", encoding="utf-8") as stream:
            if receipt.stderr_path.stat().st_size:
                stream.write("\n")
            stream.write(message + "\n")
        document = receipt.model_dump(exclude={"receipt_hash"})
        document.update(status="failed", comparable=False, error=message)
        return self._rehash_receipt(document)


    async def _run(self, tier: int, command: list[str], cwd: Path, output: Path, comparable: bool, timeout: int) -> TierReceipt:
        # Tier directories are immutable evidence. Reusing an old directory can
        # make a no-op or failed process appear successful because stale
        # checkpoint/scores files still satisfy the artifact check.
        output.mkdir(parents=True, exist_ok=False)
        stdout_path, stderr_path = output / "stdout.log", output / "stderr.log"
        started = time.perf_counter()
        process = await asyncio.create_subprocess_exec(
            *command, cwd=str(cwd), env={**os.environ, "PYTHONHASHSEED": "0", "PYTHONPATH": str(cwd / "src")},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        monitor = ResourceMonitor(process.pid)
        timed_out = False

        async def sample() -> None:
            while process.returncode is None:
                monitor.sample()
                await asyncio.sleep(1)

        sampler = asyncio.create_task(sample())
        communication = asyncio.create_task(process.communicate())
        try:
            stdout, stderr = await asyncio.wait_for(asyncio.shield(communication), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            descendants: list[psutil.Process] = []
            try:
                root = psutil.Process(process.pid)
                descendants = root.children(recursive=True)
                for child in descendants:
                    child.terminate()
                root.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            try:
                stdout, stderr = await asyncio.wait_for(communication, timeout=10)
            except asyncio.TimeoutError:
                for child in descendants:
                    with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                        child.kill()
                if process.returncode is None:
                    process.kill()
                await process.wait()
                communication.cancel()
                with suppress(asyncio.CancelledError):
                    await communication
                stdout, stderr = b"", b""
            stderr = stderr + (b"\n" if stderr else b"") + f"process timed out after {timeout}s".encode()
        finally:
            sampler.cancel()
            with suppress(asyncio.CancelledError):
                await sampler
            monitor.sample()
            monitor.close()
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        status = "timeout" if timed_out else ("succeeded" if process.returncode == 0 else "failed")
        document = {
            "receipt_id": new_id("tier"), "tier": tier, "status": status, "comparable": comparable,
            "command": command, "return_code": process.returncode, "wall_seconds": time.perf_counter() - started,
            "peak_rss_mb": monitor.peak_rss / 1024 / 1024, "peak_gpu_memory_mb": monitor.peak_gpu,
            "gpu_seconds": monitor.gpu_seconds,
            "stdout_path": stdout_path, "stderr_path": stderr_path, "output_directory": output,
            "error": (stdout.decode(errors="replace") + stderr.decode(errors="replace"))[-4000:] if status != "succeeded" else None,
        }
        return self._rehash_receipt(document)

    @staticmethod
    def _pytest_targets(workspace: Path, requested: list[str]) -> list[str]:
        target_pattern = re.compile(
            r"^tests/[A-Za-z0-9_./-]+(?:::[A-Za-z0-9_.\[\]-]+)*$"
        )
        root = workspace.resolve()
        accepted: list[str] = []
        for value in requested:
            words = value.replace("\\", "/").split()
            if "pytest" in words:
                words = words[words.index("pytest") + 1:]
            for word in words:
                if word.startswith("-") or not target_pattern.fullmatch(word):
                    continue
                relative = word.split("::", 1)[0]
                path = (root / relative).resolve()
                if root not in path.parents or not path.exists():
                    continue
                if word not in accepted:
                    accepted.append(word)
        if accepted:
            return accepted
        experiment_test = root / "tests/workflow/test_experiment.py"
        return ["tests/workflow/test_experiment.py"] if experiment_test.is_file() else []

    def _preflight_failure(self, tier: int, output: Path, message: str) -> TierReceipt:
        output.mkdir(parents=True, exist_ok=True)
        stdout_path, stderr_path = output / "stdout.log", output / "stderr.log"
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(message, encoding="utf-8")
        document = {
            "receipt_id": new_id("tier"), "tier": tier, "status": "failed", "comparable": False,
            "command": [], "return_code": None, "wall_seconds": 0.0,
            "peak_rss_mb": 0.0, "peak_gpu_memory_mb": None, "gpu_seconds": 0.0,
            "stdout_path": stdout_path, "stderr_path": stderr_path, "output_directory": output,
            "error": message[-4000:],
        }
        return self._rehash_receipt(document)

    async def tier1(self, workspace: Path, touched_files: list[str], tests: list[str], output: Path) -> TierReceipt:
        self.validator.verify_official_files()
        for relative in touched_files:
            path = workspace / relative
            if path.suffix == ".py" and path.is_file():
                # A SyntaxError in agent-generated code is a routine, expected
                # failure that must become a recoverable failed receipt. Raising
                # here previously escaped execute() entirely and killed the whole
                # run with no ledger event and no recovery.
                try:
                    compile(path.read_text(encoding="utf-8"), str(path), "exec")
                except SyntaxError as error:
                    return self._preflight_failure(1, output, f"SyntaxError in {relative}: {error}")
        targets = self._pytest_targets(workspace, tests)
        command = [sys.executable, "-m", "pytest", *targets] if targets else [sys.executable, "-m", "compileall", "-q", *touched_files]
        return await self._run(1, command, workspace, output, False, min(300, self.timeout_seconds))

    async def tier2(self, workspace: Path, transform_dir: Path, config: Path, output: Path, seed: int) -> TierReceipt:
        command = [sys.executable, "-m", "rigor_rs.training.experiment", "--transform-dir", str(transform_dir), "--config", str(config), "--output", str(output / "model"), "--max-rows", "100000", "--max-batches", "100", "--seed", str(seed)]
        receipt = await self._run(2, command, workspace, output, False, min(900, self.timeout_seconds))
        return self._validate_training_artifacts(receipt)

    async def tier3(self, workspace: Path, transform_dir: Path, config: Path, output: Path, seed: int) -> TierReceipt:
        command = [sys.executable, "-m", "rigor_rs.training.experiment", "--transform-dir", str(transform_dir), "--config", str(config), "--output", str(output / "model"), "--max-rows", str(int(self.proxy_config["maximum_rows"])), "--seed", str(seed)]
        receipt = await self._run(3, command, workspace, output, False, min(int(self.proxy_config["maximum_wall_seconds"]), self.timeout_seconds))
        return self._validate_training_artifacts(receipt)

    async def tier4(self, workspace: Path, transform_dir: Path, config: Path, output: Path, seed: int) -> TierReceipt:
        command = [sys.executable, "-m", "rigor_rs.training.experiment", "--transform-dir", str(transform_dir), "--config", str(config), "--output", str(output / "model"), "--seed", str(seed)]
        receipt = await self._run(4, command, workspace, output, True, self.timeout_seconds)
        return self._validate_training_artifacts(receipt)
