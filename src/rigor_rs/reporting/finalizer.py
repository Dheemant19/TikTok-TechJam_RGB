from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import torch

from rigor_rs.contract.challenge import ChallengeContract, sha256_file
from rigor_rs.contract.models import ComponentStatus
from rigor_rs.integrity.gates import IntegrityViolation
from rigor_rs.ledger.workflow import WorkflowLedger, canonical_hash, new_id
from rigor_rs.models.experimental import FactorizationMachine


class SubmissionFinalizer:
    def __init__(self, contract: ChallengeContract, ledger: WorkflowLedger, artifact_root: Path) -> None:
        self.contract = contract
        self.ledger = ledger
        self.artifact_root = artifact_root

    def _winner(self, session_id: str) -> tuple[str, str | None]:
        snapshot = self.ledger.snapshot(session_id)
        if not snapshot.frontier.locked or not snapshot.frontier.validation_best:
            raise RuntimeError("frontier must be locked by convergence/budget stop before packaging")
        winner = snapshot.frontier.validation_best
        if winner == "B0":
            return winner, None
        for event in reversed(self.ledger.events(session_id)):
            if event.run_id == winner and event.event_type == "frontier":
                experiment = event.payload.get("experiment_id")
                if experiment:
                    return winner, str(experiment)
        raise RuntimeError("winning experiment artifact link is missing")

    def _transform_dir(self, session_id: str) -> Path:
        for event in self.ledger.events(session_id):
            if event.component_id == "data_profiler" and event.event_type == "completed":
                return Path(event.payload["transform"]["receipt"]["path"]).parent
        raise RuntimeError("transform receipt is missing")

    def _baseline_checkpoint(self, session_id: str) -> Path:
        for event in reversed(self.ledger.events(session_id)):
            result = event.payload.get("baseline_result")
            if result and result.get("status") == "succeeded" and result.get("seeds"):
                checkpoint = Path(result["seeds"][0]["checkpoint"])
                if checkpoint.is_file():
                    return checkpoint
        raise RuntimeError("registered B0 checkpoint is missing")

    def _experiment_artifacts(self, session_id: str, winner: str) -> tuple[Path, Path]:
        checkpoint: Path | None = None
        workspace: Path | None = None
        for event in reversed(self.ledger.events(session_id)):
            if event.run_id != winner:
                continue
            if checkpoint is None and event.event_type == "tier4":
                output = event.payload.get("receipt", {}).get("output_directory")
                if output:
                    candidate = Path(output) / "model" / "checkpoint.pt"
                    if candidate.is_file():
                        checkpoint = candidate
            if workspace is None and event.component_id == "coder" and event.event_type == "completed":
                value = event.payload.get("workspace")
                if value:
                    workspace = Path(value)
            if checkpoint is not None and workspace is not None:
                return checkpoint, workspace
        raise RuntimeError("winning experiment checkpoint or workspace is missing")

    def _test_features(self, transform_dir: Path) -> tuple[dict[str, np.ndarray], list[str], list[str]]:
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
            columns=["date", "time_ms", "hourmin", "user_id", "video_id", "tab", "duration_ms"],
        ).filter(pl.col("date").is_between(lo, hi))
        users = table["user_id"].cast(pl.String).to_list()
        video_ids = table["video_id"].cast(pl.String).to_list()
        tabs = table["tab"].cast(pl.String).to_list()
        durations = table["duration_ms"].cast(pl.Float64).to_numpy()
        features = np.empty((len(users), 5), dtype=np.int32)
        for row in range(len(users)):
            values = [users[row], video_ids[row], author.get(video_ids[row], "UNK"), tabs[row], str(int(np.searchsorted(edges, durations[row])))]
            for field, value in enumerate(values):
                features[row, field] = vocabs[field].get(value, unknown[field]) + offsets[field]
        arrays = {
            "X": features,
            "users": np.asarray(users, dtype="<U128"),
            "videos": np.asarray(video_ids, dtype="<U128"),
            "date": table["date"].cast(pl.Int32).to_numpy(),
            "time_ms": table["time_ms"].cast(pl.Int64).to_numpy(),
            "hourmin": table["hourmin"].cast(pl.Int16).to_numpy(),
            "duration_ms": durations.astype(np.float32),
        }
        return arrays, users, video_ids

    @staticmethod
    def _predict_baseline(checkpoint: Path, features: np.ndarray) -> np.ndarray:
        with np.load(checkpoint, allow_pickle=False) as payload:
            factors = payload["V"]
            weights = payload["W"]
            bias = float(payload["b"])
        embeddings = factors[features]
        summed = embeddings.sum(axis=1)
        interaction = 0.5 * (
            np.square(summed).sum(axis=1)
            - np.square(embeddings).sum(axis=(1, 2))
        )
        return bias + weights[features].sum(axis=1) + interaction

    def _predict_experiment(
        self,
        workspace: Path,
        checkpoint: Path,
        test_data: Path,
        score_path: Path,
    ) -> tuple[np.ndarray, list[str], str, str]:
        source = workspace / "src/rigor_rs/training/experiment.py"
        supports_prediction = source.is_file() and "--predict-data" in source.read_text(encoding="utf-8", errors="replace")
        if supports_prediction:
            command = [
                sys.executable, "-m", "rigor_rs.training.experiment",
                "--predict-data", str(test_data), "--checkpoint", str(checkpoint),
                "--output", str(score_path),
            ]
            completed = subprocess.run(
                command,
                cwd=str(workspace),
                env={**os.environ, "PYTHONPATH": str(workspace / "src"), "PYTHONHASHSEED": "0"},
                capture_output=True,
                timeout=300,
            )
            stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
            stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
            if completed.returncode != 0:
                raise RuntimeError(f"winning-model prediction failed: {stderr}")
            scores = np.load(score_path)
            return scores, command, stdout, stderr

        # Backward-compatible safe path for older loss-only worktrees. Strict
        # state-dict loading rejects architecture changes rather than silently
        # scoring them with the base FM.
        payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
        model = FactorizationMachine(int(payload["dimension"]), int(payload["config"]["model"]["factors"]))
        model.load_state_dict(payload["state_dict"], strict=True)
        with np.load(test_data, allow_pickle=False) as data:
            features = data["X"]
        model.eval()
        with torch.no_grad():
            scores = model(torch.as_tensor(features, dtype=torch.long)).numpy()
        np.save(score_path, scores)
        return scores, ["in-process", "strict-base-fm"], "", ""

    def package(self, session_id: str) -> dict[str, Any]:
        with self.ledger.connect() as connection:
            if connection.execute("SELECT 1 FROM finalizations WHERE session_id=?", (session_id,)).fetchone():
                raise RuntimeError("session has already been finalized")
        winner, experiment_id = self._winner(session_id)
        self.contract.verify_hashes()
        final_output = self.artifact_root / "final" / session_id
        if final_output.exists():
            raise RuntimeError(f"final output already exists without a finalization receipt: {final_output}")
        staging = self.artifact_root / "final" / f".{session_id}-{new_id('staging')}"
        staging.mkdir(parents=True, exist_ok=False)
        transform_dir = self._transform_dir(session_id)
        arrays, users, videos = self._test_features(transform_dir)
        test_data = staging / "test_features.npz"
        np.savez_compressed(test_data, **arrays)

        if winner == "B0":
            checkpoint = self._baseline_checkpoint(session_id)
            values = self._predict_baseline(checkpoint, arrays["X"])
            prediction_command = ["in-process", "official-fm-checkpoint"]
            prediction_stdout = prediction_stderr = ""
        else:
            checkpoint, workspace = self._experiment_artifacts(session_id, winner)
            score_path = staging / "test_scores.npy"
            values, prediction_command, prediction_stdout, prediction_stderr = self._predict_experiment(
                workspace, checkpoint, test_data, score_path
            )
        if len(values) != len(users) or not np.isfinite(values).all():
            raise IntegrityViolation("test predictions are non-finite or have the wrong row count")

        prediction = staging / "predictions.csv"
        from rigor_rs.evaluation.official import OfficialEvaluator
        prediction_hash = OfficialEvaluator.write_predictions(prediction, users, videos, values)
        command = [
            sys.executable, str(self.contract.official_files["submission_checker"]), str(prediction),
            "--data_dir", str(self.contract.dataset_dir), "--split", "test", "--check",
        ]
        # The official checker prints non-ASCII (Chinese + "check mark") text.
        # On Windows the child process's own stdout stream defaults to the
        # OS locale codepage (cp1252) whenever stdout is a pipe rather than a
        # real console, so submit.py's own print() crashed with
        # UnicodeEncodeError before we ever got its bytes back -- this is not
        # our decode step below, it is the child's encode step. Force UTF-8
        # I/O in the child via the environment instead of touching the
        # organizer's script.
        completed = subprocess.run(
            command,
            cwd=str(self.contract.official_files["submission_checker"].parent),
            capture_output=True,
            timeout=300,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        )
        check_stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
        check_stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
        (staging / "prediction_stdout.log").write_text(prediction_stdout, encoding="utf-8")
        (staging / "prediction_stderr.log").write_text(prediction_stderr, encoding="utf-8")
        (staging / "submission_check_stdout.log").write_text(check_stdout, encoding="utf-8")
        (staging / "submission_check_stderr.log").write_text(check_stderr, encoding="utf-8")
        if completed.returncode != 0:
            raise IntegrityViolation(f"official submission check failed: {check_stderr}")
        events = self.ledger.events(session_id)
        manifest = {
            "schema_version": 1, "session_id": session_id, "validation_best": winner,
            "experiment_id": experiment_id, "checkpoint": str(checkpoint), "checkpoint_hash": sha256_file(checkpoint),
            "transform_state": str(transform_dir / "transform_state.json"),
            "transform_state_hash": sha256_file(transform_dir / "transform_state.json"),
            "predictions": str(final_output / "predictions.csv"), "predictions_hash": prediction_hash,
            "prediction_command": prediction_command,
            "official_hashes": self.contract.official_hashes,
            "schema_check": {"command": command, "stdout": check_stdout, "stderr": check_stderr, "exit_code": completed.returncode},
            "event_chain_head": events[-1].event_hash if events else None,
            "event_chain_valid": self.ledger.verify_chain(session_id),
            "created_at": datetime.now(UTC).isoformat(), "test_prediction_passes": 1,
        }
        manifest_hash = canonical_hash(manifest)
        manifest["manifest_hash"] = manifest_hash
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        staging.replace(final_output)
        manifest_path = final_output / "manifest.json"
        with self.ledger.transaction() as connection:
            connection.execute(
                "INSERT INTO finalizations VALUES(?,?,?,?)",
                (session_id, manifest_hash, str(manifest_path), datetime.now(UTC).isoformat()),
            )
            connection.execute("UPDATE sessions SET finalized=1 WHERE session_id=?", (session_id,))
        # Plan_Workflow §14.1 requires a one-way finalization event. Without it
        # a CLI-packaged session stayed "Build Final Package: Waiting" in the
        # observer forever, and the append-only chain held no record that the
        # irreversible hidden-test pass had happened.
        for component, summary in (
            ("finalizer", "Final package built and schema-checked"),
            ("submission", f"Predictions written and verified for {len(users):,} test rows"),
        ):
            self.ledger.append_event(
                session_id=session_id, run_id=winner, component_id=component,
                execution_id=f"finalization-{manifest_hash[:12]}", stage="package",
                event_type="finalized", status=ComponentStatus.SUCCEEDED,
                plain_summary=summary, payload={"manifest": manifest},
            )
        return manifest
