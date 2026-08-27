from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

from rigor_rs.contract.models import ExperimentContract, PatchProposal
from rigor_rs.integrity.gates import IntegrityViolation, PhaseBoundaryValidator


class WorkspaceManager:
    def __init__(self, repository: Path, root: Path, maximum_patch_characters: int = 60_000, maximum_reference_code_characters: int = 40_000) -> None:
        self.repository = repository.resolve()
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.maximum_patch_characters = maximum_patch_characters
        self.maximum_reference_code_characters = maximum_reference_code_characters

    def _git(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=str(cwd or self.repository), text=True,
            capture_output=True, check=check,
        )

    def create(self, experiment_id: str, parent: str = "HEAD") -> tuple[Path, str]:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", experiment_id):
            raise ValueError("unsafe experiment_id")
        path = self.root / experiment_id
        if path.exists():
            raise FileExistsError(path)
        commit = self._git("rev-parse", parent).stdout.strip()
        self._git("worktree", "add", "--detach", str(path), commit)
        return path, commit

    @staticmethod
    def diff_paths(diff: str) -> list[str]:
        paths = []
        for line in diff.splitlines():
            if line.startswith("+++ b/"):
                paths.append(line.removeprefix("+++ b/").strip())
        return list(dict.fromkeys(paths))

    def validate_proposal(self, workspace: Path, contract: ExperimentContract, proposal: PatchProposal) -> list[str]:
        diff = proposal.unified_diff
        if len(diff) > self.maximum_patch_characters:
            raise IntegrityViolation("patch exceeds configured character limit")
        if "GIT binary patch" in diff or "Binary files " in diff:
            raise IntegrityViolation("binary patches are forbidden")
        paths = self.diff_paths(diff)
        if not paths:
            raise IntegrityViolation("patch contains no file changes")
        PhaseBoundaryValidator.validate_patch_paths(paths, contract.allowed_files)
        for relative in paths:
            target = workspace / relative
            if target.exists() and target.is_symlink():
                raise IntegrityViolation(f"patch target is a symlink: {relative}")
        for dependency in proposal.dependency_changes:
            if not all((dependency.package, dependency.version, dependency.license, dependency.necessity)):
                raise IntegrityViolation("dependency changes need exact version, license, and necessity")
        return paths

    def apply(self, workspace: Path, contract: ExperimentContract, proposal: PatchProposal) -> tuple[Path, str, list[str]]:
        paths = self.validate_proposal(workspace, contract, proposal)
        patch = workspace / "diff.patch"
        patch.write_text(proposal.unified_diff, encoding="utf-8")
        self._git("apply", "--check", str(patch), cwd=workspace)
        self._git("apply", str(patch), cwd=workspace)
        digest = hashlib.sha256(patch.read_bytes()).hexdigest()
        return patch, digest, paths

    def commit(self, workspace: Path, experiment_id: str) -> str:
        self._git("add", "-A", cwd=workspace)
        self._git("-c", "user.name=RIGOR-RS", "-c", "user.email=local@rigor-rs.invalid", "commit", "-m", f"experiment {experiment_id}", cwd=workspace)
        return self._git("rev-parse", "HEAD", cwd=workspace).stdout.strip()

    def read_reference(self, repository_path: Path, files: list[str]) -> str:
        root = repository_path.resolve()
        chunks: list[str] = []
        used = 0
        for relative in files:
            path = (root / relative).resolve()
            if root not in path.parents or not path.is_file() or path.is_symlink():
                raise IntegrityViolation(f"unsafe reference-code path: {relative}")
            text = path.read_text(encoding="utf-8", errors="replace")
            remaining = self.maximum_reference_code_characters - used
            if remaining <= 0:
                break
            selected = text[:remaining]
            chunks.append(f"\n--- {relative} ---\n{selected}")
            used += len(selected)
        return "".join(chunks)
