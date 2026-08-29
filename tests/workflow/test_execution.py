from __future__ import annotations

import sys
from pathlib import Path

import pytest

from rigor_rs.training.execution import ExecutionFunnel


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
    ) == ["tests/workflow"]


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
