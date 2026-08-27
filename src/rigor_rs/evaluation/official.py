from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Sequence

import numpy as np

from rigor_rs.contract.challenge import ChallengeContract, sha256_file
from rigor_rs.contract.models import MetricReceipt
from rigor_rs.integrity.gates import IntegrityViolation, load_official_evaluator
from rigor_rs.ledger.workflow import canonical_hash, new_id


class OfficialEvaluator:
    def __init__(self, contract: ChallengeContract) -> None:
        self.contract = contract
        self.evaluator_path = contract.official_files["evaluator"]
        self.evaluator_hash = contract.official_hashes["evaluator"]
        self.evaluate_fn = load_official_evaluator(self.evaluator_path)

    def verify(self) -> None:
        if sha256_file(self.evaluator_path) != self.evaluator_hash:
            raise IntegrityViolation("official evaluator changed after contract creation")

    def score(
        self, *, run_id: str, prediction_artifact_id: str, config_hash: str,
        users: Sequence[str], labels: Sequence[float], scores: Sequence[float],
        comparable: bool = True, scope: str = "validation",
    ) -> MetricReceipt:
        self.verify()
        score_array = np.asarray(scores, dtype=np.float64)
        label_array = np.asarray(labels, dtype=np.float64)
        if len(users) != len(label_array) or len(label_array) != len(score_array):
            raise IntegrityViolation("prediction length does not match users/labels")
        if not np.isfinite(score_array).all():
            raise IntegrityViolation("predictions contain NaN/Inf")
        raw = self.evaluate_fn(list(users), label_array.tolist(), score_array.tolist())
        document = {
            "receipt_id": new_id("metric"), "run_id": run_id,
            "prediction_artifact_id": prediction_artifact_id, "evaluator_hash": self.evaluator_hash,
            "config_hash": config_hash, "gauc": float(raw["GAUC"]),
            "ndcg_at_5": float(raw["nDCG@5"]), "primary": float(raw["primary"]),
            "users": int(raw["users"]), "rows": int(raw["rows"]),
            "comparable": comparable, "scope": scope,
        }
        return MetricReceipt(**document, receipt_hash=canonical_hash(document))

    @staticmethod
    def write_predictions(path: Path, users: Sequence[str], videos: Sequence[str], scores: Sequence[float]) -> str:
        if not (len(users) == len(videos) == len(scores)):
            raise IntegrityViolation("prediction columns are not aligned")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["row_id", "user_id", "video_id", "score"])
            for row_id, (user, video, score) in enumerate(zip(users, videos, scores)):
                value = float(score)
                if not np.isfinite(value):
                    raise IntegrityViolation("prediction contains NaN/Inf")
                writer.writerow([row_id, user, video, f"{value:.9g}"])
        temporary.replace(path)
        return sha256_file(path)

    @staticmethod
    def validate_prediction_csv(path: Path, users: Sequence[str], videos: Sequence[str]) -> list[float]:
        values: list[float] = []
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ["row_id", "user_id", "video_id", "score"]:
                raise IntegrityViolation("prediction CSV header mismatch")
            for expected, row in enumerate(reader):
                if int(row["row_id"]) != expected:
                    raise IntegrityViolation("row_id is not continuous")
                if expected >= len(users) or row["user_id"] != users[expected] or row["video_id"] != videos[expected]:
                    raise IntegrityViolation("prediction identifiers are misaligned")
                value = float(row["score"])
                if not np.isfinite(value):
                    raise IntegrityViolation("prediction contains NaN/Inf")
                values.append(value)
        if len(values) != len(users):
            raise IntegrityViolation("prediction row count mismatch")
        return values
