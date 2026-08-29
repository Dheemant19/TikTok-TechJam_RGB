from __future__ import annotations

import argparse
import json
import os
import random
import time
from pathlib import Path

import numpy as np
import torch
import yaml
from torch.nn import functional as F

from rigor_rs.integrity.gates import load_official_evaluator
from rigor_rs.models.experimental import FactorizationMachine


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


def bpr_pairs(users: np.ndarray, labels: np.ndarray, rng: np.random.Generator, limit: int | None = None) -> tuple[np.ndarray, np.ndarray]:
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
                f"(torch={torch.__version__}, torch.version.cuda={torch.version.cuda!r}). "
                "Install the project-pinned CUDA wheel and verify the NVIDIA driver."
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


def train(transform_dir: Path, config_path: Path, output: Path, max_rows: int | None = None, max_batches: int | None = None, seed: int = 0) -> dict:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    set_deterministic(seed)
    train_data = load_npz(transform_dir / "train.npz", max_rows)
    valid_data = load_npz(transform_dir / "valid.npz", max_rows)
    device = resolve_device(str(config.get("device", "auto")))
    if device.type == "cuda":
        torch.cuda.set_device(device)
        torch.cuda.reset_peak_memory_stats(device)
    dimension = int(max(train_data["X"].max(initial=0), valid_data["X"].max(initial=0)) + 1)
    model = FactorizationMachine(dimension, int(config["model"]["factors"])).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(config["training"]["learning_rate"]), weight_decay=float(config["training"].get("weight_decay", 0.0)))
    batch_size = int(config["training"]["batch_size"])
    loss_name = config["training"]["loss"]
    evaluate = load_official_evaluator(Path(config["official_evaluator"]))
    rng = np.random.default_rng(seed)
    best_primary = -np.inf
    best_state = None
    history = []
    started = time.perf_counter()
    for epoch in range(1, int(config["training"]["epochs"]) + 1):
        model.train()
        losses = []
        if loss_name == "bpr":
            positive, negative = bpr_pairs(train_data["users"], train_data["y"], rng, max_rows)
            order = rng.permutation(len(positive))
            batches = [(positive[order[i:i + batch_size]], negative[order[i:i + batch_size]]) for i in range(0, len(order), batch_size)]
            for batch_index, (pos, neg) in enumerate(batches):
                optimizer.zero_grad(set_to_none=True)
                positive_score = model(torch.as_tensor(train_data["X"][pos], device=device, dtype=torch.long))
                negative_score = model(torch.as_tensor(train_data["X"][neg], device=device, dtype=torch.long))
                loss = -F.logsigmoid(positive_score - negative_score).mean()
                loss.backward(); optimizer.step()
                losses.append(float(loss.detach().cpu()))
                if max_batches and batch_index + 1 >= max_batches:
                    break
        else:
            order = rng.permutation(len(train_data["y"]))
            for batch_index, start in enumerate(range(0, len(order), batch_size)):
                index = order[start:start + batch_size]
                optimizer.zero_grad(set_to_none=True)
                logits = model(torch.as_tensor(train_data["X"][index], device=device, dtype=torch.long))
                labels = torch.as_tensor(train_data["y"][index], device=device, dtype=torch.float32)
                loss = F.binary_cross_entropy_with_logits(logits, labels)
                loss.backward(); optimizer.step()
                losses.append(float(loss.detach().cpu()))
                if max_batches and batch_index + 1 >= max_batches:
                    break
        model.eval()
        with torch.no_grad():
            predictions = []
            for start in range(0, len(valid_data["X"]), 200_000):
                predictions.append(model(torch.as_tensor(valid_data["X"][start:start + 200_000], device=device, dtype=torch.long)).cpu().numpy())
        scores = np.concatenate(predictions)
        metrics = evaluate(valid_data["users"].tolist(), valid_data["y"].tolist(), scores.tolist())
        history.append({"epoch": epoch, "loss": float(np.mean(losses)), "metrics": metrics})
        if metrics["primary"] > best_primary + 1e-5:
            best_primary = metrics["primary"]
            best_state = {key: value.detach().cpu() for key, value in model.state_dict().items()}
        elif len(history) - max(i for i, value in enumerate(history) if value["metrics"]["primary"] == best_primary) >= int(config["training"].get("patience", 3)):
            break
    if best_state is None:
        raise RuntimeError("training produced no checkpoint")
    model.load_state_dict(best_state)
    output.mkdir(parents=True, exist_ok=True)
    checkpoint_tmp = output / "checkpoint.pt.tmp"
    torch.save({"state_dict": best_state, "dimension": dimension, "config": config}, checkpoint_tmp)
    checkpoint_tmp.replace(output / "checkpoint.pt")
    model.to(device).eval()
    with torch.no_grad():
        scores = model(torch.as_tensor(valid_data["X"], device=device, dtype=torch.long)).cpu().numpy()
    np.save(output / "valid_scores.npy", scores)
    result = {
        "status": "succeeded", "loss": loss_name, "seed": seed, "device": str(device),
        "device_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "cuda_version": torch.version.cuda if device.type == "cuda" else None,
        "compute_capability": list(torch.cuda.get_device_capability(device)) if device.type == "cuda" else None,
        "rows_train": len(train_data["y"]), "rows_valid": len(valid_data["y"]),
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "best_primary": best_primary, "history": history, "wall_seconds": time.perf_counter() - started,
        "peak_gpu_memory_mb": torch.cuda.max_memory_allocated(device) / 1024 / 1024 if device.type == "cuda" else None,
    }
    (output / "train_receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transform-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    print(json.dumps(train(args.transform_dir, args.config, args.output, args.max_rows, args.max_batches, args.seed), sort_keys=True))


if __name__ == "__main__":
    main()
