from __future__ import annotations

from pathlib import Path

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
