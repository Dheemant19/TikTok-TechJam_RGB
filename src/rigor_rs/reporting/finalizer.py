from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import torch

from rigor_rs.contract.challenge import ChallengeContract, sha256_file
from rigor_rs.integrity.gates import IntegrityViolation
from rigor_rs.ledger.workflow import WorkflowLedger, canonical_hash
from rigor_rs.models.experimental import FactorizationMachine


class SubmissionFinalizer:
    def __init__(self, contract: ChallengeContract, ledger: WorkflowLedger, artifact_root: Path) -> None:
        self.contract = contract
        self.ledger = ledger
        self.artifact_root = artifact_root

    def _winner(self, session_id: str) -> tuple[str, str]:
        snapshot = self.ledger.snapshot(session_id)
        if not snapshot.frontier.locked or not snapshot.frontier.validation_best:
            raise RuntimeError("frontier must be locked by convergence/budget stop before packaging")
        winner = snapshot.frontier.validation_best
        for event in reversed(self.ledger.events(session_id)):
            if event.run_id == winner and event.event_type == "frontier":
                experiment = event.payload.get("experiment_id")
                if experiment:
                    return winner, experiment
        if winner == "B0":
            raise RuntimeError("baseline-only finalization requires a registered B0 checkpoint")
        raise RuntimeError("winning experiment artifact link is missing")

    def _transform_dir(self, session_id: str) -> Path:
        for event in self.ledger.events(session_id):
            if event.component_id == "data_profiler" and event.event_type == "completed":
                return Path(event.payload["transform"]["receipt"]["path"]).parent
        raise RuntimeError("transform receipt is missing")

    def _test_features(self, transform_dir: Path) -> tuple[np.ndarray, list[str], list[str]]:
        state = json.loads((transform_dir / "transform_state.json").read_text(encoding="utf-8"))
        vocabs = state["vocabularies"]
        unknown = state["unknown_ids"]
        offsets = state["offsets"]
        edges = np.asarray(state["duration_bucket_edges"])
        videos = pl.read_csv(self.contract.dataset_dir / "video_features_basic_pure.csv", columns=["video_id", "author_id"])
        author = dict(zip(videos["video_id"].cast(pl.String).to_list(), videos["author_id"].cast(pl.String).to_list()))
        lo, hi = self.contract.splits["test"]
        # Feature-only projection: long_view and all feedback labels are never read.
        table = pl.read_csv(
            self.contract.dataset_dir / "log_standard_4_22_to_5_08_pure.csv",
            columns=["date", "user_id", "video_id", "tab", "duration_ms"],
        ).filter(pl.col("date").is_between(lo, hi))
        users = table["user_id"].cast(pl.String).to_list()
        video_ids = table["video_id"].cast(pl.String).to_list()
        tabs = table["tab"].cast(pl.String).to_list()
        durations = table["duration_ms"].cast(pl.Float64).to_list()
        features = np.empty((len(users), 5), dtype=np.int32)
        for row in range(len(users)):
            values = [users[row], video_ids[row], author.get(video_ids[row], "UNK"), tabs[row], str(int(np.searchsorted(edges, durations[row])))]
            for field, value in enumerate(values):
                features[row, field] = vocabs[field].get(value, unknown[field]) + offsets[field]
        return features, users, video_ids

    def package(self, session_id: str) -> dict[str, Any]:
        with self.ledger.connect() as connection:
            if connection.execute("SELECT 1 FROM finalizations WHERE session_id=?", (session_id,)).fetchone():
                raise RuntimeError("session has already been finalized")
        winner, experiment_id = self._winner(session_id)
        self.contract.verify_hashes()
        output = self.artifact_root / "final" / session_id
        output.mkdir(parents=True, exist_ok=False)
        checkpoint = self.artifact_root / "runs" / experiment_id / "tier4/model/checkpoint.pt"
        if not checkpoint.is_file():
            raise RuntimeError(f"winning checkpoint missing: {checkpoint}")
        transform_dir = self._transform_dir(session_id)
        features, users, videos = self._test_features(transform_dir)
        payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
        model = FactorizationMachine(int(payload["dimension"]), int(payload["config"]["model"]["factors"]))
        model.load_state_dict(payload["state_dict"]); model.eval()
        scores = []
        with torch.no_grad():
            for start in range(0, len(features), 200_000):
                scores.append(model(torch.as_tensor(features[start:start + 200_000], dtype=torch.long)).numpy())
        values = np.concatenate(scores)
        prediction = output / "predictions.csv"
        from rigor_rs.evaluation.official import OfficialEvaluator
        prediction_hash = OfficialEvaluator.write_predictions(prediction, users, videos, values)
        command = [
            sys.executable, str(self.contract.official_files["submission_checker"]), str(prediction),
            "--data_dir", str(self.contract.dataset_dir), "--split", "test", "--check",
        ]
        completed = subprocess.run(command, cwd=str(self.contract.official_files["submission_checker"].parent), text=True, capture_output=True, timeout=300)
        if completed.returncode != 0:
            raise IntegrityViolation(f"official submission check failed: {completed.stderr}")
        events = self.ledger.events(session_id)
        manifest = {
            "schema_version": 1, "session_id": session_id, "validation_best": winner,
            "experiment_id": experiment_id, "checkpoint": str(checkpoint), "checkpoint_hash": sha256_file(checkpoint),
            "transform_state": str(transform_dir / "transform_state.json"),
            "transform_state_hash": sha256_file(transform_dir / "transform_state.json"),
            "predictions": str(prediction), "predictions_hash": prediction_hash,
            "official_hashes": self.contract.official_hashes,
            "schema_check": {"command": command, "stdout": completed.stdout, "exit_code": completed.returncode},
            "event_chain_head": events[-1].event_hash if events else None,
            "event_chain_valid": self.ledger.verify_chain(session_id),
            "created_at": datetime.now(UTC).isoformat(), "test_prediction_passes": 1,
        }
        manifest_hash = canonical_hash(manifest)
        manifest["manifest_hash"] = manifest_hash
        manifest_path = output / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        with self.ledger.transaction() as connection:
            connection.execute(
                "INSERT INTO finalizations VALUES(?,?,?,?)",
                (session_id, manifest_hash, str(manifest_path), datetime.now(UTC).isoformat()),
            )
            connection.execute("UPDATE sessions SET finalized=1 WHERE session_id=?", (session_id,))
        return manifest
