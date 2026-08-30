from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from rigor_rs.contract.challenge import ChallengeContract, sha256_file
from rigor_rs.contract.models import MetricReceipt
from rigor_rs.evaluation.official import OfficialEvaluator
from rigor_rs.ledger.workflow import canonical_hash, new_id
from rigor_rs.integrity.gates import load_official_evaluator


def _load_fm_class(path: Path):
    starter = str(path.parent)
    sys.path.insert(0, starter)
    try:
        spec = importlib.util.spec_from_file_location("rigor_official_baseline", path)
        if not spec or not spec.loader:
            raise ImportError(path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.FM
    finally:
        sys.path.remove(starter)

def _load_split(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as data:
        return {key: data[key] for key in data.files}

def _write_progress(path: Path | None, document: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)



def _fit_fm(
    fm_class: Any,
    evaluate_fn: Any,
    cfg: dict[str, Any],
    train: dict[str, Any],
    valid: dict[str, Any],
    seed: int,
    shuffled: bool = False,
    progress_path: Path | None = None,
) -> tuple[Any, list[dict[str, Any]]]:
    started = time.perf_counter()
    Xtr, ytr = train["X"], train["y"].copy()
    Xva, yva = valid["X"], valid["y"]
    if shuffled:
        ytr = np.random.default_rng(seed).permutation(ytr)
    dimension = int(max(Xtr.max(initial=0), Xva.max(initial=0)) + 1)
    model = fm_class(dimension, k=int(cfg["k"]), lr=float(cfg["lr"]), seed=seed)
    rng = np.random.default_rng(seed)
    best = -np.inf
    best_state = None
    bad = 0
    history = []
    for epoch in range(1, int(cfg["max_epochs"]) + 1):
        order = rng.permutation(len(ytr))
        losses = [
            model.step(
                Xtr[order[i:i + int(cfg["batch"])]],
                ytr[order[i:i + int(cfg["batch"])]],
            )
            for i in range(0, len(order), int(cfg["batch"]))
        ]
        scores = model.predict(Xva)
        raw = evaluate_fn(valid["users"].tolist(), yva.tolist(), scores.tolist())
        progress = {
            "seed": seed,
            "status": "running",
            "epoch": epoch,
            "max_epochs": int(cfg["max_epochs"]),
            "loss": float(np.mean(losses)),
            "primary": float(raw["primary"]),
            "elapsed_seconds": time.perf_counter() - started,
        }
        history.append(
            {"epoch": epoch, "loss": progress["loss"], "primary": progress["primary"]}
        )
        _write_progress(progress_path, progress)
        if raw["primary"] > best + 1e-5:
            best, bad = raw["primary"], 0
            best_state = (model.V.copy(), model.W.copy(), np.float32(model.b))
        else:
            bad += 1
            if bad >= int(cfg["patience"]):
                break
    if best_state is None:
        raise RuntimeError("FM failed to produce a checkpoint")
    model.V, model.W, model.b = best_state
    _write_progress(
        progress_path,
        {
            "seed": seed,
            "status": "completed",
            "epoch": len(history),
            "max_epochs": int(cfg["max_epochs"]),
            "loss": history[-1]["loss"],
            "primary": history[-1]["primary"],
            "best_primary": max(item["primary"] for item in history),
            "elapsed_seconds": time.perf_counter() - started,
        },
    )
    return model, history


def _fit_seed_process(
    job: tuple[Path, Path, dict[str, Any], Path, Path, int],
) -> tuple[int, np.ndarray, np.ndarray, np.float32, list[dict[str, Any]]]:
    baseline_path, evaluator_path, cfg, transform_dir, output_dir, seed = job
    model, history = _fit_fm(
        _load_fm_class(baseline_path),
        load_official_evaluator(evaluator_path),
        cfg,
        _load_split(transform_dir / "train.npz"),
        _load_split(transform_dir / "valid.npz"),
        seed,
        progress_path=output_dir / f"progress_seed_{seed}.json",
    )
    return seed, model.V, model.W, np.float32(model.b), history


class BaselineReproducer:
    def __init__(self, contract: ChallengeContract, config_path: Path, artifact_root: Path) -> None:
        self.contract = contract
        self.config_path = config_path
        self.config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        self.artifact_root = artifact_root
        self.evaluator = OfficialEvaluator(contract)
        self.FM = _load_fm_class(contract.official_files["baseline"])

    @staticmethod
    def _load_split(path: Path) -> dict[str, Any]:
        return _load_split(path)

    def _fit_one(
        self,
        train: dict[str, Any],
        valid: dict[str, Any],
        seed: int,
        shuffled: bool = False,
        progress_path: Path | None = None,
    ):
        return _fit_fm(
            self.FM,
            self.evaluator.evaluate_fn,
            self.contract.baseline_config,
            train,
            valid,
            seed,
            shuffled,
            progress_path,
        )

    def _fit_seeds(
        self,
        train: dict[str, Any],
        valid: dict[str, Any],
        transform_dir: Path,
        output_dir: Path,
        seeds: list[int],
        workers: int,
    ) -> list[tuple[int, Any, list[dict[str, Any]]]]:
        if workers == 1:
            return [
                (
                    seed,
                    *self._fit_one(
                        train,
                        valid,
                        seed,
                        progress_path=output_dir / f"progress_seed_{seed}.json",
                    ),
                )
                for seed in seeds
            ]

        self.evaluator.verify()
        jobs = [
            (
                self.contract.official_files["baseline"],
                self.contract.official_files["evaluator"],
                self.contract.baseline_config,
                transform_dir,
                output_dir,
                seed,
            )
            for seed in seeds
        ]
        with ProcessPoolExecutor(max_workers=workers) as executor:
            fitted_states = list(executor.map(_fit_seed_process, jobs))

        fitted = []
        for seed, factors, weights, bias, history in fitted_states:
            model = self.FM(
                len(weights),
                k=int(self.contract.baseline_config["k"]),
                lr=float(self.contract.baseline_config["lr"]),
                seed=seed,
            )
            model.V, model.W, model.b = factors, weights, bias
            fitted.append((seed, model, history))
        return fitted


    def reproduce(self, transform_dir: Path, *, seeds: list[int] | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        train = self._load_split(transform_dir / "train.npz")
        valid = self._load_split(transform_dir / "valid.npz")
        output = self.artifact_root / "baseline" / new_id("B0")
        output.mkdir(parents=True, exist_ok=True)
        configured_seeds = seeds or list(self.config["seed_policy"]["seeds"])
        if not configured_seeds:
            raise ValueError("baseline seed policy must contain at least one seed")
        workers = min(
            len(configured_seeds),
            max(1, int(self.config.get("parallel_seed_workers", 1))),
        )
        fitted_seeds = self._fit_seeds(
            train, valid, transform_dir, output, configured_seeds, workers
        )
        receipts: list[MetricReceipt] = []
        seed_runs = []
        config_hash = sha256_file(self.config_path)
        for seed, model, history in fitted_seeds:
            prediction_path = output / f"valid_seed_{seed}.csv"
            scores = model.predict(valid["X"])
            prediction_hash = self.evaluator.write_predictions(prediction_path, valid["users"].tolist(), valid["videos"].tolist(), scores)
            receipt = self.evaluator.score(
                run_id=f"B0-seed-{seed}", prediction_artifact_id=prediction_hash,
                config_hash=config_hash, users=valid["users"].tolist(),
                labels=valid["y"].tolist(), scores=scores,
            )
            checkpoint = output / f"fm_seed_{seed}.npz"
            np.savez_compressed(checkpoint, V=model.V, W=model.W, b=model.b)
            (output / f"history_seed_{seed}.json").write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
            receipts.append(receipt)
            seed_runs.append({"seed": seed, "metrics": receipt.model_dump(mode="json"), "checkpoint": str(checkpoint), "prediction": str(prediction_path)})
        mean_primary = float(np.mean([item.primary for item in receipts]))
        reference = float(self.contract.baseline_valid["primary"])
        tolerance = float(self.config["acceptance"]["absolute_primary_tolerance"])
        passed = abs(mean_primary - reference) <= tolerance
        result = {
            "run_id": "B0", "status": "succeeded" if passed else "failed",
            "reference_primary": reference, "observed_mean_primary": mean_primary,
            "absolute_difference": abs(mean_primary - reference), "tolerance": tolerance,
            "seeds": seed_runs, "wall_seconds": time.perf_counter() - started,
            "parallel_seed_workers": workers,
            "starter_hashes": self.contract.official_hashes,
            "environment": {"python": sys.version, "numpy": np.__version__},
        }
        result["result_hash"] = canonical_hash(result)
        (output / "baseline_receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result

    def harness_checks(self, transform_dir: Path, seed: int = 0) -> dict[str, MetricReceipt]:
        train = self._load_split(transform_dir / "train.npz")
        valid = self._load_split(transform_dir / "valid.npz")
        rng = np.random.default_rng(seed)
        random_scores = rng.random(len(valid["y"]))
        counts: dict[str, list[float]] = {}
        for video, label in zip(train["videos"].tolist(), train["y"].tolist()):
            value = counts.setdefault(str(video), [0.0, 0.0])
            value[0] += float(label); value[1] += 1.0
        global_rate = float(np.mean(train["y"]))
        popularity = np.asarray([(counts.get(str(video), [0, 0])[0] + 20 * global_rate) / (counts.get(str(video), [0, 0])[1] + 20) for video in valid["videos"].tolist()])
        config_hash = sha256_file(self.config_path)
        return {
            "random": self.evaluator.score(run_id="harness-random", prediction_artifact_id="memory", config_hash=config_hash, users=valid["users"].tolist(), labels=valid["y"].tolist(), scores=random_scores),
            "item_popularity": self.evaluator.score(run_id="harness-pop", prediction_artifact_id="memory", config_hash=config_hash, users=valid["users"].tolist(), labels=valid["y"].tolist(), scores=popularity),
        }

    def label_shuffle_control(self, transform_dir: Path, seed: int = 314159) -> dict[str, Any]:
        train = self._load_split(transform_dir / "train.npz")
        valid = self._load_split(transform_dir / "valid.npz")
        model, _ = self._fit_one(train, valid, seed, shuffled=True)
        receipt = self.evaluator.score(
            run_id="sanity-label-shuffle", prediction_artifact_id="memory",
            config_hash=sha256_file(self.config_path), users=valid["users"].tolist(),
            labels=valid["y"].tolist(), scores=model.predict(valid["X"]), comparable=False,
        )
        random_bound = float(
            json.loads(
                self.contract.official_files["baseline_scores"].read_text(encoding="utf-8")
            )["scores"]["random"]["valid"]["primary"]
        ) + self.contract.sanity_shuffle_tolerance
        return {"receipt": receipt.model_dump(mode="json"), "bound": random_bound, "passed": receipt.primary <= random_bound, "seed": seed}
