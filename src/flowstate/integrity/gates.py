from __future__ import annotations

import csv
import hashlib
import importlib.util
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from flowstate.contract.challenge import ChallengeContract, sha256_file
from flowstate.contract.models import DataArtifact, SplitTaint


class IntegrityViolation(RuntimeError):
    pass


PROTECTED_PATHS = {
    "kuairand-starter-kit/evaluate.py", "kuairand-starter-kit/data.py",
    "kuairand-starter-kit/baseline_scores.json", "configs/challenge/kuairand_pure.yaml",
    "kuairand-1k-starter-kit/data.py", "kuairand-1k-starter-kit/submit.py",
    "kuairand-1k-starter-kit/baseline_scores.json", "configs/challenge/kuairand_1k.yaml",
    "src/flowstate/data/kuairand_1k.py",
}


class PhaseBoundaryValidator:
    def __init__(self, contract: ChallengeContract) -> None:
        self.contract = contract

    def verify_official_files(self) -> None:
        try:
            self.contract.verify_hashes()
        except RuntimeError as error:
            raise IntegrityViolation(str(error)) from error

    def validate_artifact(self, artifact: DataArtifact, allowed_taints: set[SplitTaint]) -> None:
        if not artifact.path.exists():
            raise IntegrityViolation(f"artifact path does not exist: {artifact.path}")
        if not artifact.taints <= allowed_taints:
            raise IntegrityViolation(f"taint escalation: {sorted(artifact.taints - allowed_taints)}")
        if sha256_file(artifact.path) != artifact.source_hash:
            raise IntegrityViolation("artifact source hash mismatch")
        if artifact.row_count < 0:
            raise IntegrityViolation("negative row count")

    @staticmethod
    def validate_arrays(features: np.ndarray, labels: np.ndarray | None = None) -> None:
        if features.ndim != 2 or not np.isfinite(features).all():
            raise IntegrityViolation("features must be a finite 2D array")
        if labels is not None:
            if labels.ndim != 1 or len(labels) != len(features) or not np.isfinite(labels).all():
                raise IntegrityViolation("labels must be finite and align with features")

    @staticmethod
    def validate_row_ids(row_ids: Iterable[int], expected_rows: int) -> None:
        values = list(row_ids)
        if values != list(range(expected_rows)):
            raise IntegrityViolation("row_id must be continuous and zero-based")

    @staticmethod
    def validate_join(before_rows: int, after_rows: int, permitted_ratio: float = 1.0) -> None:
        if before_rows == 0 and after_rows:
            raise IntegrityViolation("join created rows from empty input")
        ratio = after_rows / before_rows if before_rows else 1.0
        if ratio > permitted_ratio:
            raise IntegrityViolation(f"join expansion ratio {ratio:.4f} exceeds {permitted_ratio:.4f}")

    def validate_dates(self, dates: Iterable[int], split: str) -> None:
        lo, hi = self.contract.splits[split]
        invalid = [value for value in dates if not lo <= int(value) <= hi]
        if invalid:
            raise IntegrityViolation(f"{split} contains dates outside [{lo},{hi}]")

    @staticmethod
    def validate_patch_paths(paths: Iterable[str], allowed_files: Iterable[str]) -> None:
        allowed = {Path(item).as_posix() for item in allowed_files}
        for raw in paths:
            path = Path(raw)
            normalized = path.as_posix()
            if path.is_absolute() or ".." in path.parts:
                raise IntegrityViolation(f"unsafe patch path: {raw}")
            if normalized in PROTECTED_PATHS or normalized.startswith(("runs/", "state/", "artifacts/")):
                raise IntegrityViolation(f"protected patch path: {raw}")
            if normalized not in allowed:
                raise IntegrityViolation(f"path outside experiment contract: {raw}")


def load_official_evaluator(path: Path):
    spec = importlib.util.spec_from_file_location("flowstate_official_evaluate", path)
    if not spec or not spec.loader:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.evaluate


def evaluator_metamorphic_checks(contract: ChallengeContract) -> dict[str, bool]:
    evaluate = load_official_evaluator(contract.official_files["evaluator"])
    users = ["u1", "u1", "u1", "u2", "u2", "u3", "u3"]
    labels = [1, 0, 1, 0, 0, 1, 1]
    scores = [0.9, 0.1, 0.7, 0.4, 0.3, 0.6, 0.5]
    base = evaluate(users, labels, scores)
    order = [3, 0, 5, 2, 6, 1, 4]
    reordered = evaluate([users[i] for i in order], [labels[i] for i in order], [scores[i] for i in order])
    shifted = evaluate(users, labels, [value + 17.0 for value in scores])
    promoted = scores.copy()
    promoted[2] = 1.1
    promoted_result = evaluate(users, labels, promoted)
    return {
        "row_order_invariant": all(abs(base[key] - reordered[key]) < 1e-12 for key in ("GAUC", "nDCG@5", "primary")),
        "constant_shift_invariant": all(abs(base[key] - shifted[key]) < 1e-12 for key in ("GAUC", "nDCG@5", "primary")),
        "positive_rank_monotonic": promoted_result["nDCG@5"] + 1e-12 >= base["nDCG@5"],
        "all_negative_ndcg_zero": evaluate(["u"] * 3, [0, 0, 0], [0.3, 0.2, 0.1])["nDCG@5"] == 0.0,
        "single_class_gauc_default": evaluate(["u"] * 3, [1, 1, 1], [0.3, 0.2, 0.1])["GAUC"] == 0.5,
    }
