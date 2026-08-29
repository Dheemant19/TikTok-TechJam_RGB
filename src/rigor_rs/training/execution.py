from __future__ import annotations

import asyncio
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
    stdout_path: Path
    stderr_path: Path
    output_directory: Path
    error: str | None = None
    receipt_hash: str


class ResourceMonitor:
    def __init__(self, pid: int) -> None:
        self.process = psutil.Process(pid)
        self.peak_rss = 0
        self.peak_gpu: float | None = None
        self._nvml_ready = False
        if pynvml:
            try:
                pynvml.nvmlInit()
                self._nvml_ready = True
            except Exception:
                pass

    def sample(self) -> None:
        try:
            processes = [self.process, *self.process.children(recursive=True)]
            self.peak_rss = max(self.peak_rss, sum(item.memory_info().rss for item in processes if item.is_running()))
            if self._nvml_ready:
                total = 0
                for index in range(pynvml.nvmlDeviceGetCount()):
                    handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                    for item in pynvml.nvmlDeviceGetComputeRunningProcesses(handle):
                        if item.pid in {process.pid for process in processes}:
                            total += item.usedGpuMemory
                self.peak_gpu = max(self.peak_gpu or 0, total / 1024 / 1024)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

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

    async def _run(self, tier: int, command: list[str], cwd: Path, output: Path, comparable: bool, timeout: int) -> TierReceipt:
        output.mkdir(parents=True, exist_ok=True)
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
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            try:
                root = psutil.Process(process.pid)
                for child in root.children(recursive=True):
                    child.terminate()
                root.terminate()
            except psutil.NoSuchProcess:
                pass
            await process.wait()
            stdout, stderr = b"", b"process timed out"
        finally:
            sampler.cancel()
            monitor.sample(); monitor.close()
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        status = "timeout" if timed_out else ("succeeded" if process.returncode == 0 else "failed")
        document = {
            "receipt_id": new_id("tier"), "tier": tier, "status": status, "comparable": comparable,
            "command": command, "return_code": process.returncode, "wall_seconds": time.perf_counter() - started,
            "peak_rss_mb": monitor.peak_rss / 1024 / 1024, "peak_gpu_memory_mb": monitor.peak_gpu,
            "stdout_path": stdout_path, "stderr_path": stderr_path, "output_directory": output,
            "error": (stdout.decode(errors="replace") + stderr.decode(errors="replace"))[-4000:] if status != "succeeded" else None,
        }
        return TierReceipt(**document, receipt_hash=canonical_hash({key: str(value) for key, value in document.items()}))

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
        return accepted or ["tests/workflow"]


    async def tier1(self, workspace: Path, touched_files: list[str], tests: list[str], output: Path) -> TierReceipt:
        self.validator.verify_official_files()
        for relative in touched_files:
            path = workspace / relative
            if path.suffix == ".py":
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
        targets = self._pytest_targets(workspace, tests)
        command = [sys.executable, "-m", "pytest", *targets]
        return await self._run(1, command, workspace, output, False, min(300, self.timeout_seconds))

    async def tier2(self, workspace: Path, transform_dir: Path, config: Path, output: Path, seed: int) -> TierReceipt:
        command = [sys.executable, "-m", "rigor_rs.training.experiment", "--transform-dir", str(transform_dir), "--config", str(config), "--output", str(output / "model"), "--max-rows", "100000", "--max-batches", "100", "--seed", str(seed)]
        return await self._run(2, command, workspace, output, False, min(900, self.timeout_seconds))

    async def tier3(self, workspace: Path, transform_dir: Path, config: Path, output: Path, seed: int) -> TierReceipt:
        command = [sys.executable, "-m", "rigor_rs.training.experiment", "--transform-dir", str(transform_dir), "--config", str(config), "--output", str(output / "model"), "--max-rows", str(int(self.proxy_config["maximum_rows"])), "--seed", str(seed)]
        return await self._run(3, command, workspace, output, False, min(int(self.proxy_config["maximum_wall_seconds"]), self.timeout_seconds))

    async def tier4(self, workspace: Path, transform_dir: Path, config: Path, output: Path, seed: int) -> TierReceipt:
        command = [sys.executable, "-m", "rigor_rs.training.experiment", "--transform-dir", str(transform_dir), "--config", str(config), "--output", str(output / "model"), "--seed", str(seed)]
        return await self._run(4, command, workspace, output, True, self.timeout_seconds)
