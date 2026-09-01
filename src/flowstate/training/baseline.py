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

from flowstate.contract.challenge import ChallengeContract, sha256_file
from flowstate.contract.models import MetricReceipt
from flowstate.evaluation.official import OfficialEvaluator
from flowstate.ledger.workflow import canonical_hash, new_id
from flowstate.integrity.gates import load_official_evaluator


def _load_fm_class(path: Path):
    starter = str(path.parent)
    sys.path.insert(0, starter)
    try:
        spec = importlib.util.spec_from_file_location("flowstate_official_baseline", path)
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


class _TorchOfficialFM:
    """Run the organizer FM equations with Torch's device-optimized tensor kernels."""

    def __init__(self, model: Any, execution_device: str) -> None:
        import torch

        self._torch = torch
        device_name = "cpu" if execution_device == "torch_cpu" else execution_device
        self.device = torch.device(device_name)
        self.lr = float(model.lr)
        self.l2 = float(model.l2)
        self.t = int(model.t)
        self._V = torch.from_numpy(model.V).to(self.device)
        self._W = torch.from_numpy(model.W).to(self.device)
        self._mV = torch.zeros_like(self._V)
        self._vV = torch.zeros_like(self._V)
        self._mW = torch.zeros_like(self._W)
        self._vW = torch.zeros_like(self._W)
        self._b = np.float32(model.b)
        self._finalized = False

    def _batch_values(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        indices = self._torch.as_tensor(X, dtype=self._torch.long, device=self.device)
        embeddings = self._V[indices].cpu().numpy()
        weights = self._W[indices].cpu().numpy()
        summed = embeddings.sum(axis=1)
        logits = (
            self._b
            + weights.sum(axis=1)
            + 0.5
            * (
                np.square(summed).sum(axis=1)
                - np.square(embeddings).sum(axis=(1, 2))
            )
        )
        return logits, embeddings, summed

    def step(self, X: np.ndarray, y: np.ndarray) -> float:
        batch_size = len(y)
        logits, embeddings, summed = self._batch_values(X)
        probabilities = 1.0 / (1.0 + np.exp(-np.clip(logits, -30, 30)))
        gradient = ((probabilities - y) / batch_size).astype(np.float32)

        flat_indices = np.asarray(X, dtype=np.int64).reshape(-1)
        unique_indices, inverse = np.unique(flat_indices, return_inverse=True)
        repeated_gradient = np.repeat(gradient, X.shape[1])
        weight_updates = np.zeros(len(unique_indices), dtype=np.float32)
        np.add.at(weight_updates, inverse, repeated_gradient)
        factor_updates = np.zeros(
            (len(unique_indices), embeddings.shape[2]), dtype=np.float32
        )
        contributions = (
            gradient[:, None, None] * (summed[:, None, :] - embeddings)
        ).reshape(-1, embeddings.shape[2])
        np.add.at(factor_updates, inverse, contributions)

        torch = self._torch
        touched = torch.from_numpy(unique_indices).to(self.device)
        with torch.no_grad():
            factor_gradient = self._V.mul(self.l2)
            factor_gradient[touched] += torch.from_numpy(factor_updates).to(self.device)
            weight_gradient = self._W.mul(self.l2)
            weight_gradient[touched] += torch.from_numpy(weight_updates).to(self.device)

            self.t += 1
            beta1, beta2, epsilon = 0.9, 0.999, 1e-8
            beta1_correction = 1.0 - beta1 ** self.t
            beta2_correction = 1.0 - beta2 ** self.t
            for parameter, grad, first, second in (
                (self._V, factor_gradient, self._mV, self._vV),
                (self._W, weight_gradient, self._mW, self._vW),
            ):
                first.mul_(beta1).add_(grad, alpha=1.0 - beta1)
                second.mul_(beta2).addcmul_(grad, grad, value=1.0 - beta2)
                denominator = second.div(beta2_correction).sqrt_().add_(epsilon)
                parameter.addcdiv_(
                    first,
                    denominator,
                    value=-self.lr / beta1_correction,
                )
            self._b -= self.lr * gradient.sum()

        return float(
            -np.mean(
                y * np.log(probabilities + 1e-9)
                + (1 - y) * np.log(1 - probabilities + 1e-9)
            )
        )

    def predict(self, X: np.ndarray, bs: int = 200_000) -> np.ndarray:
        if self._finalized:
            values = []
            for start in range(0, len(X), bs):
                batch = X[start:start + bs]
                embeddings = self.V[batch]
                summed = embeddings.sum(axis=1)
                values.append(
                    self.b
                    + self.W[batch].sum(axis=1)
                    + 0.5
                    * (
                        np.square(summed).sum(axis=1)
                        - np.square(embeddings).sum(axis=(1, 2))
                    )
                )
            return np.concatenate(values)
        return np.concatenate(
            [self._batch_values(X[start:start + bs])[0] for start in range(0, len(X), bs)]
        )

    def checkpoint(self) -> tuple[Any, Any, np.float32]:
        return self._V.clone(), self._W.clone(), np.float32(self._b)

    def restore(self, state: tuple[Any, Any, np.float32]) -> None:
        self._V, self._W, self._b = state

    def finalize(self) -> None:
        self.V = self._V.cpu().numpy().copy()
        self.W = self._W.cpu().numpy().copy()
        self.b = np.float32(self._b)
        del self._V, self._W, self._mV, self._vV, self._mW, self._vW
        self._finalized = True


def _resolve_execution_device(requested: str) -> str:
    normalized = requested.casefold()
    if normalized not in {"auto", "cpu", "cuda", "mps"}:
        raise ValueError(f"unsupported baseline execution device: {requested}")
    if normalized == "cpu":
        return "cpu"
    import torch

    mps_backend = getattr(torch.backends, "mps", None)
    mps_available = bool(mps_backend and mps_backend.is_available())
    if normalized == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("baseline execution requested CUDA, but CUDA is unavailable")
        return "cuda"
    if normalized == "mps":
        if not mps_available:
            raise RuntimeError("baseline execution requested MPS, but MPS is unavailable")
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    if mps_available:
        return "mps"
    return "torch_cpu"


def _model_checkpoint(model: Any) -> Any:
    if isinstance(model, _TorchOfficialFM):
        return model.checkpoint()
    return model.V.copy(), model.W.copy(), np.float32(model.b)


def _restore_model(model: Any, state: Any) -> None:
    if isinstance(model, _TorchOfficialFM):
        model.restore(state)
        model.finalize()
        return
    model.V, model.W, model.b = state

def _is_accelerator_failure(error: BaseException, execution_device: str) -> bool:
    if execution_device not in {"cuda", "mps"}:
        return False
    message = f"{type(error).__name__}: {error}".casefold()
    indicators = (
        execution_device,
        "out of memory",
        "device",
        "backend",
        "allocation",
        "not implemented",
    )
    return any(indicator in message for indicator in indicators)






def _fit_fm(
    fm_class: Any,
    evaluate_fn: Any,
    cfg: dict[str, Any],
    train: dict[str, Any],
    valid: dict[str, Any],
    seed: int,
    shuffled: bool = False,
    progress_path: Path | None = None,
    execution_device: str = "cpu",
) -> tuple[Any, list[dict[str, Any]]]:
    started = time.perf_counter()
    Xtr, ytr = train["X"], train["y"].copy()
    Xva, yva = valid["X"], valid["y"]
    if shuffled:
        ytr = np.random.default_rng(seed).permutation(ytr)
    dimension = int(max(Xtr.max(initial=0), Xva.max(initial=0)) + 1)
    official_model = fm_class(dimension, k=int(cfg["k"]), lr=float(cfg["lr"]), seed=seed)
    model = (
        _TorchOfficialFM(official_model, execution_device)
        if execution_device != "cpu"
        else official_model
    )
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
            best_state = _model_checkpoint(model)
        else:
            bad += 1
            if bad >= int(cfg["patience"]):
                break
    if best_state is None:
        raise RuntimeError("FM failed to produce a checkpoint")
    _restore_model(model, best_state)
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
    job: tuple[Path, Path, dict[str, Any], Path, Path, int, str],
) -> tuple[int, np.ndarray, np.ndarray, np.float32, list[dict[str, Any]]]:
    baseline_path, evaluator_path, cfg, transform_dir, output_dir, seed, execution_device = job
    model, history = _fit_fm(
        _load_fm_class(baseline_path),
        load_official_evaluator(evaluator_path),
        cfg,
        _load_split(transform_dir / "train.npz"),
        _load_split(transform_dir / "valid.npz"),
        seed,
        progress_path=output_dir / f"progress_seed_{seed}.json",
        execution_device=execution_device,
    )
    return seed, model.V, model.W, np.float32(model.b), history


class BaselineReproducer:
    def __init__(self, contract: ChallengeContract, config_path: Path, artifact_root: Path) -> None:
        self.contract = contract
        self.config_path = config_path
        self.config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        self.execution_device = _resolve_execution_device(
            str(self.config.get("execution_device", "cpu"))
        )
        self.artifact_root = artifact_root
        self.evaluator = OfficialEvaluator(contract)
        self.FM = _load_fm_class(contract.official_files["baseline"])
        self.requested_execution_device = str(
            self.config.get("execution_device", "cpu")
        ).casefold()

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
            shuffled=shuffled,
            progress_path=progress_path,
            execution_device=self.execution_device,
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
                self.execution_device,
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

    def _fit_seeds_with_fallback(
        self,
        train: dict[str, Any],
        valid: dict[str, Any],
        transform_dir: Path,
        output_dir: Path,
        seeds: list[int],
        workers: int,
    ) -> tuple[list[tuple[int, Any, list[dict[str, Any]]]], dict[str, str] | None]:
        try:
            return (
                self._fit_seeds(
                    train, valid, transform_dir, output_dir, seeds, workers
                ),
                None,
            )
        except (RuntimeError, MemoryError) as error:
            if (
                self.requested_execution_device != "auto"
                or not _is_accelerator_failure(error, self.execution_device)
            ):
                raise
            failed_device = self.execution_device
            self.execution_device = "torch_cpu"
            recovery = {
                "error": f"{type(error).__name__}: {error}",
                "action": f"retry baseline on torch_cpu after {failed_device} failure",
                "result": "recovered",
            }
            _write_progress(
                output_dir / "device_fallback.json",
                recovery,
            )
            fitted = self._fit_seeds(
                train, valid, transform_dir, output_dir, seeds, workers=1
            )
            return fitted, recovery




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
        fitted_seeds, device_fallback = self._fit_seeds_with_fallback(
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
        if self.contract.baseline_reference_mode == "reproduced":
            reference = mean_primary
            tolerance = 0.0
            passed = True
        else:
            reference = float(self.contract.baseline_valid["primary"])
            tolerance = float(self.config["acceptance"]["absolute_primary_tolerance"])
            passed = abs(mean_primary - reference) <= tolerance
        result = {
            "run_id": "B0", "status": "succeeded" if passed else "failed",
            "reference_primary": reference, "observed_mean_primary": mean_primary,
            "absolute_difference": abs(mean_primary - reference), "tolerance": tolerance,
            "reference_mode": self.contract.baseline_reference_mode,
            "seeds": seed_runs, "wall_seconds": time.perf_counter() - started,
            "parallel_seed_workers": workers,
            "execution_device": self.execution_device,
            "device_fallback": device_fallback,
            "starter_hashes": self.contract.official_hashes,
            "environment": {
                "python": sys.version,
                "numpy": np.__version__,
                "execution_device": self.execution_device,
            },
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
        if getattr(self.contract, "baseline_reference_mode", "published") == "reproduced":
            random_scores = np.random.default_rng(seed).random(len(valid["y"]))
            random_receipt = self.evaluator.score(
                run_id="sanity-random-bound",
                prediction_artifact_id="memory",
                config_hash=sha256_file(self.config_path),
                users=valid["users"].tolist(),
                labels=valid["y"].tolist(),
                scores=random_scores,
                comparable=False,
            )
            random_primary = random_receipt.primary
        else:
            random_primary = float(
                json.loads(
                    self.contract.official_files["baseline_scores"].read_text(encoding="utf-8")
                )["scores"]["random"]["valid"]["primary"]
            )
        bound = random_primary + self.contract.sanity_shuffle_tolerance
        return {"receipt": receipt.model_dump(mode="json"), "bound": bound, "passed": receipt.primary <= bound, "seed": seed}
