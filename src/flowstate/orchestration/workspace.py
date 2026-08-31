from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

from flowstate.contract.models import ExperimentContract, PatchProposal
from flowstate.integrity.gates import IntegrityViolation, PhaseBoundaryValidator


_RUNTIME_SPARSE_PATTERNS = (
    "/src/flowstate/",
    "/configs/experiments/",
    "/kuairand-starter-kit/evaluate.py",
    "/pyproject.toml",
)


class WorkspaceManager:
    def __init__(self, repository: Path, root: Path, maximum_patch_characters: int = 60_000, maximum_reference_code_characters: int = 40_000) -> None:
        self.repository = repository.resolve()
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.maximum_patch_characters = maximum_patch_characters
        self.maximum_reference_code_characters = maximum_reference_code_characters

    def _git(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args], cwd=str(cwd or self.repository), text=True,
            capture_output=True, check=False,
        )
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip() or "no diagnostic output"
            raise RuntimeError(
                f"git {' '.join(args)} failed with exit code {result.returncode}: {detail}"
            )
        return result

    @staticmethod
    def _sparse_patterns(required_paths: list[str] | None) -> list[str]:
        patterns = list(_RUNTIME_SPARSE_PATTERNS)
        for raw in required_paths or []:
            path = Path(raw)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe sparse-checkout path: {raw}")
            normalized = path.as_posix().strip("/")
            if normalized:
                patterns.append(f"/{normalized}")
        return list(dict.fromkeys(patterns))

    def _materialize_flowstate_package(self, workspace: Path) -> None:
        """Copy the live `src/flowstate` tree into the worktree so the Code
        Agent's own patched files are actually what a training subprocess
        imports, instead of silently falling back to the outer repository's
        editable install.

        `flowstate` has never been committed under that name in this
        repository's git history (`git log --all -- src/flowstate/__init__.py`
        is empty; every commit tracks it as `src/rigor_rs`), so sparse
        checkout from any commit can never populate it -- `git worktree add`
        only ever produces the stale placeholder package. Without a real
        `src/flowstate/__init__.py` on disk, the worktree's `flowstate` is an
        empty PEP 420 namespace-package fragment; Python's import resolution
        gives a *regular* package found later in `sys.path` (the outer
        repository, reached via its `.pth` editable-install entry) priority
        over a namespace-package portion found earlier -- so `import
        flowstate` silently resolves to the outer repository for every
        submodule, not just the ones the sparse checkout above already
        missed. The whole package must be self-contained here for isolation
        to be real: PhaseBoundaryValidator still restricts what the Code
        Agent's patch may modify (`contract.allowed_files`); this only
        supplies the supporting library code untouched by that patch.
        """
        source_root = (self.repository / "src" / "flowstate").resolve()
        if not source_root.is_dir():
            return
        target_root = (workspace / "src" / "flowstate").resolve()
        target_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source_root, target_root, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    def _materialize_required_sources(self, workspace: Path, required_paths: list[str] | None) -> None:
        """Copy the caller's current allowed source files into a worktree.

        A worktree starts from HEAD, while an operator may have staged or
        otherwise uncommitted experiment files that the active workflow uses.
        Snapshot those explicitly allowed files so the Code Agent receives the
        same source it will patch and cannot mistakenly add an existing file.
        Files under `src/flowstate/` are already covered by
        `_materialize_flowstate_package`; this handles paths outside it
        (configs, tests).
        """
        root = workspace.resolve()
        for raw in required_paths or []:
            relative = Path(raw)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"unsafe source materialization path: {raw}")
            if relative.as_posix().startswith("src/flowstate/"):
                continue
            source = (self.repository / relative).resolve()
            target = (root / relative).resolve()
            if root not in target.parents:
                raise IntegrityViolation(f"unsafe source materialization path: {raw}")
            if not source.exists():
                continue
            if source.is_symlink() or not source.is_file():
                raise IntegrityViolation(f"source materialization requires a regular file: {raw}")
            if target.exists() and target.is_symlink():
                raise IntegrityViolation(f"source materialization target is a symlink: {raw}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def create(
        self,
        experiment_id: str,
        parent: str = "HEAD",
        required_paths: list[str] | None = None,
    ) -> tuple[Path, str]:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", experiment_id):
            raise ValueError("unsafe experiment_id")
        path = self.root / experiment_id
        if path.exists():
            raise FileExistsError(path)
        commit = self._git("rev-parse", parent).stdout.strip()
        self._git("worktree", "add", "--detach", "--no-checkout", str(path), commit)
        try:
            self._git("sparse-checkout", "init", "--no-cone", cwd=path)
            self._git(
                "sparse-checkout", "set", "--no-cone",
                *self._sparse_patterns(required_paths),
                cwd=path,
            )
            self._git("checkout", "--detach", commit, cwd=path)
            self._materialize_flowstate_package(path)
            self._materialize_required_sources(path, required_paths)
        except Exception:
            self._git("worktree", "remove", "--force", str(path), check=False)
            raise
        return path, commit

    @staticmethod
    def diff_paths(diff: str) -> list[str]:
        paths = []
        for line in diff.splitlines():
            if line.startswith("+++ b/"):
                paths.append(line.removeprefix("+++ b/").strip())
        return list(dict.fromkeys(paths))

    @staticmethod
    def _safe_workspace_target(workspace: Path, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise IntegrityViolation(f"unsafe workspace path: {relative}")
        root = workspace.resolve()
        target = (root / path).resolve()
        if root not in target.parents:
            raise IntegrityViolation(f"unsafe workspace path: {relative}")
        return target

    def restore_sources(
        self,
        workspace: Path,
        allowed_files: list[str],
        source_context: dict[str, str],
    ) -> None:
        """Restore the exact source snapshot used to generate a patch."""
        unexpected = set(source_context) - set(allowed_files)
        if unexpected:
            raise IntegrityViolation(f"source context contains files outside contract: {sorted(unexpected)}")
        for relative in allowed_files:
            target = self._safe_workspace_target(workspace, relative)
            if target.exists() and target.is_symlink():
                raise IntegrityViolation(f"source restore target is a symlink: {relative}")
            if relative not in source_context:
                if target.exists():
                    if not target.is_file():
                        raise IntegrityViolation(f"source restore target is not a regular file: {relative}")
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(source_context[relative])

    def validate_proposal(self, workspace: Path, contract: ExperimentContract, proposal: PatchProposal) -> list[str]:
        diff = proposal.unified_diff
        if len(diff) > self.maximum_patch_characters:
            raise IntegrityViolation("patch exceeds configured character limit")
        if "GIT binary patch" in diff or "Binary files " in diff:
            raise IntegrityViolation("binary patches are forbidden")
        paths = self.diff_paths(diff)
        if not paths:
            raise IntegrityViolation("patch contains no file changes")
        hunk_headers = [line for line in diff.splitlines() if line.startswith("@@")]
        valid_hunk = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(?: .*)?$")
        if not hunk_headers or any(not valid_hunk.fullmatch(line) for line in hunk_headers):
            raise IntegrityViolation(
                "patch has an invalid unified-diff hunk header; bare @@ is forbidden"
            )
        PhaseBoundaryValidator.validate_patch_paths(paths, contract.allowed_files)
        new_file_paths: list[str] = []
        declares_new_file = False
        for line in diff.splitlines():
            if line.startswith("diff --git "):
                declares_new_file = False
            elif line.startswith("new file mode "):
                declares_new_file = True
            elif declares_new_file and line.startswith("+++ b/"):
                new_file_paths.append(line.removeprefix("+++ b/").strip())
        for relative in new_file_paths:
            if (workspace / relative).exists():
                raise IntegrityViolation(f"patch declares an existing file as new: {relative}")
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
        patch_directory = self.root.parent / "patches" / workspace.name
        patch_directory.mkdir(parents=True, exist_ok=True)
        patch = patch_directory / "diff.patch"
        with patch.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(proposal.unified_diff)
        originals: dict[str, bytes | None] = {}
        for relative in paths:
            target = self._safe_workspace_target(workspace, relative)
            originals[relative] = target.read_bytes() if target.is_file() else None
        check = self._git("apply", "--check", str(patch), cwd=workspace, check=False)
        if check.returncode != 0:
            detail = (check.stderr or check.stdout).strip()
            raise IntegrityViolation(f"patch failed git apply --check: {detail}")
        self._git("apply", str(patch), cwd=workspace)
        # A patch can apply cleanly and still produce invalid Python: the agent
        # returns file content inside a JSON string, so a single-escaped "\n"
        # decodes into a real newline inside a string literal. Compile-check
        # here so the Code Agent gets a repair round-trip with the exact
        # SyntaxError, instead of it surfacing later as an uncaught crash.
        for relative in paths:
            target = workspace / relative
            if target.suffix != ".py" or not target.is_file():
                continue
            try:
                compile(target.read_text(encoding="utf-8"), str(target), "exec")
            except SyntaxError as error:
                for original_relative, content in originals.items():
                    original_target = self._safe_workspace_target(workspace, original_relative)
                    if content is None:
                        if original_target.exists():
                            original_target.unlink()
                    else:
                        original_target.parent.mkdir(parents=True, exist_ok=True)
                        original_target.write_bytes(content)
                raise IntegrityViolation(f"patched {relative} is not valid Python: {error}") from error
        digest = hashlib.sha256(patch.read_bytes()).hexdigest()
        return patch, digest, paths

    def revert(self, workspace: Path) -> None:
        self._git("checkout", "--", ".", cwd=workspace, check=False)

    def file_at_head(self, workspace: Path, relative: str) -> str:
        result = self._git("show", f"HEAD:{relative}", cwd=workspace, check=False)
        return result.stdout if result.returncode == 0 else ""

    def commit(self, workspace: Path, experiment_id: str, paths: list[str]) -> str:
        if not paths:
            raise IntegrityViolation("cannot commit an experiment with no validated files")
        for raw in paths:
            path = Path(raw)
            if path.is_absolute() or ".." in path.parts:
                raise IntegrityViolation(f"unsafe commit path: {raw}")
        self._git("add", "--", *paths, cwd=workspace)
        self._git("-c", "user.name=FlowState", "-c", "user.email=local@flowstate.invalid", "commit", "-m", f"experiment {experiment_id}", cwd=workspace)
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
