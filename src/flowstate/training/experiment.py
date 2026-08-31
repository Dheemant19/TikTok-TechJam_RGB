from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml
from torch.nn import functional as F

from flowstate.integrity.gates import load_official_evaluator
from flowstate.models.experimental import build_candidate_model
from flowstate.training.candidate_features import (
    chronological_positive_histories,
    histories_from_state,
    load_history_state,
    serialize_history_state,
)


def set_deterministic(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    torch.backends.cudnn.benchmark = False


def load_npz(path: Path, maximum_rows: int | None = None) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as data:
        result = {key: data[key] for key in data.files}
    if maximum_rows:
        result = {key: value[:maximum_rows] for key, value in result.items()}
    return result


def bpr_pairs(
    users: np.ndarray,
    labels: np.ndarray,
    rng: np.random.Generator,
    limit: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    groups: dict[str, tuple[list[int], list[int]]] = {}
    for index, (user, label) in enumerate(zip(users.tolist(), labels.tolist())):
        positive, negative = groups.setdefault(str(user), ([], []))
        (positive if label > 0 else negative).append(index)
    positives: list[int] = []
    negatives: list[int] = []
    for positive, negative in groups.values():
        if not positive or not negative:
            continue
        for index in positive:
            positives.append(index)
            negatives.append(int(rng.choice(negative)))
            if limit and len(positives) >= limit:
                return np.asarray(positives), np.asarray(negatives)
    return np.asarray(positives), np.asarray(negatives)


def resolve_device(requested: str) -> torch.device:
    value = requested.strip().lower()
    if value == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if value == "cpu":
        return torch.device("cpu")
    if value == "cuda" or value.startswith("cuda:"):
        if not torch.cuda.is_available():
            raise RuntimeError(
                f"device={requested!r} requires CUDA, but this PyTorch build cannot access a CUDA GPU "
                f"(torch={torch.__version__}, torch.version.cuda={torch.version.cuda!r})"
            )
        device = torch.device(value)
        index = device.index if device.index is not None else torch.cuda.current_device()
        if index >= torch.cuda.device_count():
            raise RuntimeError(
                f"device={requested!r} selects GPU index {index}, but only "
                f"{torch.cuda.device_count()} CUDA device(s) are visible"
            )
        return torch.device("cuda", index)
    raise ValueError(f"unsupported device {requested!r}; expected auto, cpu, cuda, or cuda:<index>")


def build_model(dimension: int, field_count: int, config: dict[str, Any]) -> torch.nn.Module:
    return build_candidate_model(dimension, field_count, config)


def _main_scores(output: torch.Tensor | dict[str, torch.Tensor]) -> torch.Tensor:
    if isinstance(output, dict):
        if "long_view" not in output:
            raise ValueError("multi-output model must provide a long_view score")
        return output["long_view"]
    return output


def _forward(
    model: torch.nn.Module,
    features: torch.Tensor,
    history: torch.Tensor | None = None,
    history_mask: torch.Tensor | None = None,
) -> torch.Tensor | dict[str, torch.Tensor]:
    if bool(getattr(model, "requires_history", False)):
        return model(features, history, history_mask)
    return model(features)


def _batch_history(
    histories: np.ndarray | None,
    masks: np.ndarray | None,
    indices: np.ndarray,
    device: torch.device,
) -> tuple[torch.Tensor | None, torch.Tensor | None]:
    if histories is None or masks is None:
        return None, None
    return (
        torch.as_tensor(histories[indices], device=device, dtype=torch.long),
        torch.as_tensor(masks[indices], device=device, dtype=torch.bool),
    )


def _pointwise_loss(
    output: torch.Tensor | dict[str, torch.Tensor],
    labels: torch.Tensor,
    train_data: dict[str, np.ndarray],
    indices: np.ndarray,
    training_config: dict[str, Any],
    device: torch.device,
) -> torch.Tensor:
    loss = F.binary_cross_entropy_with_logits(_main_scores(output), labels)
    auxiliary_tasks = [str(value) for value in training_config.get("auxiliary_tasks", [])]
    if not auxiliary_tasks:
        return loss
    if not isinstance(output, dict):
        raise ValueError("auxiliary_tasks require a model with separate named output heads")
    weights = dict(training_config.get("auxiliary_weights", {}))
    for task in auxiliary_tasks:
        if task not in train_data:
            raise ValueError(f"auxiliary task {task!r} is not available in training data")
        if task not in output:
            raise ValueError(f"model did not produce the configured auxiliary head {task!r}")
        targets = torch.as_tensor(train_data[task][indices], device=device, dtype=torch.float32)
        loss = loss + float(weights.get(task, 0.1)) * F.binary_cross_entropy_with_logits(output[task], targets)
    return loss


def _predict_scores(
    model: torch.nn.Module,
    data: dict[str, np.ndarray],
    device: torch.device,
    histories: np.ndarray | None,
    masks: np.ndarray | None,
) -> np.ndarray:
    predictions: list[np.ndarray] = []
    for start in range(0, len(data["X"]), 200_000):
        stop = min(start + 200_000, len(data["X"]))
        index = np.arange(start, stop)
        history, history_mask = _batch_history(histories, masks, index, device)
        output = _forward(
            model,
            torch.as_tensor(data["X"][start:stop], device=device, dtype=torch.long),
            history,
            history_mask,
        )
        predictions.append(_main_scores(output).detach().cpu().numpy())
    return np.concatenate(predictions)


def train(
    transform_dir: Path,
    config_path: Path,
    output: Path,
    max_rows: int | None = None,
    max_batches: int | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    set_deterministic(seed)
    train_data = load_npz(transform_dir / "train.npz", max_rows)
    valid_data = load_npz(transform_dir / "valid.npz", max_rows)
    device = resolve_device(str(config.get("device", "auto")))
    if device.type == "cuda":
        torch.cuda.set_device(device)
        torch.cuda.reset_peak_memory_stats(device)
    dimension = int(max(train_data["X"].max(initial=0), valid_data["X"].max(initial=0)) + 1)
    field_count = int(train_data["X"].shape[1])
    model = build_model(dimension, field_count, config).to(device)
    model_family = str(getattr(model, "model_family", config.get("model", {}).get("name", type(model).__name__)))
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(config["training"]["learning_rate"]),
        weight_decay=float(config["training"].get("weight_decay", 0.0)),
    )
    batch_size = int(config["training"]["batch_size"])
    loss_name = str(config["training"].get("loss", "bce"))
    evaluate = load_official_evaluator(Path(config["official_evaluator"]))
    rng = np.random.default_rng(seed)
    best_primary = -np.inf
    best_state: dict[str, torch.Tensor] | None = None
    best_epoch = 0
    history: list[dict[str, Any]] = []
    started = time.perf_counter()
    maximum_seconds = float(config["training"].get("maximum_seconds", 0))

    train_histories = train_masks = valid_histories = valid_masks = None
    history_state: dict[str, list[int]] = {}
    history_length = int(config.get("model", {}).get("history_length", 50))
    if bool(getattr(model, "requires_history", False)):
        train_histories, train_masks, history_state = chronological_positive_histories(train_data, history_length)
        valid_histories, valid_masks = histories_from_state(valid_data["users"], history_state, history_length)

    stop_for_time = False
    for epoch in range(1, int(config["training"]["epochs"]) + 1):
        model.train()
        losses: list[float] = []
        if loss_name == "bpr":
            positive, negative = bpr_pairs(train_data["users"], train_data["y"], rng, max_rows)
            order = rng.permutation(len(positive))
            batches = [
                (positive[order[index:index + batch_size]], negative[order[index:index + batch_size]])
                for index in range(0, len(order), batch_size)
            ]
            for batch_index, (positive_index, negative_index) in enumerate(batches):
                optimizer.zero_grad(set_to_none=True)
                positive_history, positive_mask = _batch_history(train_histories, train_masks, positive_index, device)
                negative_history, negative_mask = _batch_history(train_histories, train_masks, negative_index, device)
                positive_score = _main_scores(_forward(model, torch.as_tensor(train_data["X"][positive_index], device=device, dtype=torch.long), positive_history, positive_mask))
                negative_score = _main_scores(_forward(model, torch.as_tensor(train_data["X"][negative_index], device=device, dtype=torch.long), negative_history, negative_mask))
                loss = -F.logsigmoid(positive_score - negative_score).mean()
                loss.backward()
                optimizer.step()
                losses.append(float(loss.detach().cpu()))
                if max_batches and batch_index + 1 >= max_batches:
                    break
                if maximum_seconds and time.perf_counter() - started >= maximum_seconds:
                    stop_for_time = True
                    break
        else:
            order = rng.permutation(len(train_data["y"]))
            for batch_index, start in enumerate(range(0, len(order), batch_size)):
                index = order[start:start + batch_size]
                optimizer.zero_grad(set_to_none=True)
                batch_history, batch_mask = _batch_history(train_histories, train_masks, index, device)
                output_scores = _forward(
                    model,
                    torch.as_tensor(train_data["X"][index], device=device, dtype=torch.long),
                    batch_history,
                    batch_mask,
                )
                labels = torch.as_tensor(train_data["y"][index], device=device, dtype=torch.float32)
                loss = _pointwise_loss(output_scores, labels, train_data, index, config["training"], device)
                loss.backward()
                optimizer.step()
                losses.append(float(loss.detach().cpu()))
                if max_batches and batch_index + 1 >= max_batches:
                    break
                if maximum_seconds and time.perf_counter() - started >= maximum_seconds:
                    stop_for_time = True
                    break
        if not losses:
            raise RuntimeError("training completed no optimization batches")
        model.eval()
        with torch.no_grad():
            scores = _predict_scores(model, valid_data, device, valid_histories, valid_masks)
        metrics = evaluate(valid_data["users"].tolist(), valid_data["y"].tolist(), scores.tolist())
        history.append({"epoch": epoch, "loss": float(np.mean(losses)), "metrics": metrics})
        if metrics["primary"] > best_primary + 1e-5:
            best_primary = float(metrics["primary"])
            best_epoch = epoch
            best_state = {key: value.detach().cpu() for key, value in model.state_dict().items()}
        elif epoch - best_epoch >= int(config["training"].get("patience", 3)):
            break
        if stop_for_time:
            break

    if best_state is None:
        raise RuntimeError("training produced no checkpoint")
    model.load_state_dict(best_state)
    output.mkdir(parents=True, exist_ok=True)
    checkpoint_tmp = output / "checkpoint.pt.tmp"
    checkpoint_payload: dict[str, Any] = {
        "state_dict": best_state,
        "dimension": dimension,
        "field_count": field_count,
        "config": config,
        "model_family": model_family,
    }
    if bool(getattr(model, "requires_history", False)):
        checkpoint_payload["history_state"] = serialize_history_state(history_state, history_length)
    torch.save(checkpoint_payload, checkpoint_tmp)
    checkpoint_tmp.replace(output / "checkpoint.pt")
    model.to(device).eval()
    with torch.no_grad():
        scores = _predict_scores(model, valid_data, device, valid_histories, valid_masks)
    if not np.isfinite(scores).all() or float(np.std(scores)) <= 1e-8:
        raise RuntimeError("model produced non-finite or constant validation scores")
    np.save(output / "valid_scores.npy", scores)
    result = {
        "status": "succeeded",
        "model_family": model_family,
        "loss": loss_name,
        "auxiliary_heads": list(config["training"].get("auxiliary_tasks", [])),
        "uses_chronological_history": bool(getattr(model, "requires_history", False)),
        "seed": seed,
        "device": str(device),
        "device_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "cuda_version": torch.version.cuda if device.type == "cuda" else None,
        "compute_capability": list(torch.cuda.get_device_capability(device)) if device.type == "cuda" else None,
        "rows_train": len(train_data["y"]),
        "rows_valid": len(valid_data["y"]),
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "best_primary": best_primary,
        "history": history,
        "stopped_for_time_limit": stop_for_time,
        "wall_seconds": time.perf_counter() - started,
        "peak_gpu_memory_mb": torch.cuda.max_memory_allocated(device) / 1024 / 1024 if device.type == "cuda" else None,
    }
    (output / "train_receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def predict(checkpoint_path: Path, data_path: Path, output_path: Path) -> dict[str, Any]:
    data = load_npz(data_path)
    payload = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    field_count = int(payload.get("field_count", data["X"].shape[1]))
    config = payload["config"]
    requested_device = str(config.get("device", "auto"))
    device = resolve_device(requested_device)
    model = build_model(int(payload["dimension"]), field_count, config)
    model.load_state_dict(payload["state_dict"], strict=True)
    model.to(device)
    model.eval()
    histories = masks = None
    if bool(getattr(model, "requires_history", False)):
        history_state, history_length = load_history_state(payload["history_state"])
        histories, masks = histories_from_state(data["users"], history_state, history_length)
    with torch.no_grad():
        scores = _predict_scores(model, data, device, histories, masks)
    if not np.isfinite(scores).all() or float(np.std(scores)) <= 1e-8:
        raise RuntimeError("prediction produced non-finite or constant scores")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(output_path, scores)
    return {
        "status": "succeeded",
        "rows": len(scores),
        "checkpoint": str(checkpoint_path),
        "model_family": payload.get(
            "model_family",
            str(payload.get("config", {}).get("model", {}).get("name", "factorization_machine")),
        ),
        "data": str(data_path),
        "scores": str(output_path),
        "device": str(device),
        "device_name": torch.cuda.get_device_name(device) if device.type == "cuda" else "CPU",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transform-dir", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--predict-data", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    args = parser.parse_args()
    if args.predict_data or args.checkpoint:
        if not args.predict_data or not args.checkpoint:
            parser.error("--predict-data and --checkpoint must be supplied together")
        result = predict(args.checkpoint, args.predict_data, args.output)
    else:
        if not args.transform_dir or not args.config:
            parser.error("--transform-dir and --config are required for training")
        result = train(args.transform_dir, args.config, args.output, args.max_rows, args.max_batches, args.seed)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
