from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
import yaml

from flowstate.models.experimental import build_candidate_model
from flowstate.training.candidate_features import chronological_positive_histories, histories_from_state
from flowstate.training.experiment import predict, train


def test_builtin_model_families_produce_one_score_per_candidate() -> None:
    features = torch.tensor([[1, 6, 11, 16, 21], [2, 7, 12, 17, 22]], dtype=torch.long)
    history = torch.tensor([[0, 0, 5], [0, 6, 7]], dtype=torch.long)
    mask = torch.tensor([[False, False, True], [False, True, True]])

    for name in ("factorization_machine", "deepfm", "dcnv2"):
        model = build_candidate_model(32, 5, {"model": {"name": name, "factors": 4}, "training": {}})
        output = model(features)
        assert isinstance(output, torch.Tensor)
        assert output.shape == (2,)

    din = build_candidate_model(
        32,
        5,
        {"model": {"name": "din", "factors": 4, "hidden_dimension": 16}, "training": {}},
    )
    assert din(features, history, mask).shape == (2,)


def test_multi_task_model_uses_separate_named_heads() -> None:
    model = build_candidate_model(
        32,
        5,
        {
            "model": {"name": "deepfm", "factors": 4, "hidden_dimensions": [16]},
            "training": {"auxiliary_tasks": ["is_click", "is_like"]},
        },
    )
    output = model(torch.tensor([[1, 6, 11, 16, 21]], dtype=torch.long))
    assert isinstance(output, dict)
    assert set(output) == {"long_view", "is_click", "is_like"}


def test_chronological_history_never_contains_current_positive() -> None:
    data = {
        "X": np.asarray([[1, 10], [1, 11], [1, 12]], dtype=np.int32),
        "y": np.asarray([1, 0, 1], dtype=np.float32),
        "users": np.asarray(["u", "u", "u"]),
        "date": np.asarray([20220408, 20220408, 20220408], dtype=np.int32),
        "time_ms": np.asarray([100, 200, 300], dtype=np.int64),
    }
    histories, masks, state = chronological_positive_histories(data, 3)

    assert not masks[0].any()
    assert histories[1, masks[1]].tolist() == [10]
    assert histories[2, masks[2]].tolist() == [10]
    assert state == {"u": [10, 12]}


def _synthetic_transform(path: Path) -> None:
    rng = np.random.default_rng(7)
    users = np.repeat(np.arange(8), 8).astype(str)
    videos = np.tile(np.arange(8), 8).astype(str)
    features = np.column_stack(
        (
            np.repeat(np.arange(8), 8),
            8 + np.tile(np.arange(8), 8),
            16 + np.tile(np.arange(4), 16),
            20 + np.tile(np.arange(2), 32),
            22 + np.tile(np.arange(3), 22)[:64],
        )
    ).astype(np.int32)
    labels = ((np.arange(64) + np.repeat(np.arange(8), 8)) % 3 == 0).astype(np.float32)
    common = {
        "X": features,
        "y": labels,
        "users": users,
        "videos": videos,
        "date": np.full(64, 20220408, dtype=np.int32),
        "time_ms": np.arange(64, dtype=np.int64),
        "hourmin": np.zeros(64, dtype=np.int16),
        "duration_ms": np.full(64, 10_000, dtype=np.float32),
    }
    np.savez_compressed(
        path / "train.npz",
        **common,
        play_time_ms=rng.uniform(0, 10_000, 64).astype(np.float32),
        is_click=labels.astype(np.int8),
        is_like=np.zeros(64, dtype=np.int8),
        is_follow=np.zeros(64, dtype=np.int8),
        is_comment=np.zeros(64, dtype=np.int8),
        is_forward=np.zeros(64, dtype=np.int8),
        is_hate=np.zeros(64, dtype=np.int8),
    )
    np.savez_compressed(path / "valid.npz", **common)


def test_deepfm_training_checkpoint_predicts_without_labels(tmp_path: Path) -> None:
    _synthetic_transform(tmp_path)
    config = {
        "official_evaluator": str(Path("kuairand-starter-kit/evaluate.py").resolve()),
        "model": {"name": "deepfm", "factors": 4, "hidden_dimensions": [16]},
        "training": {
            "loss": "bce",
            "learning_rate": 0.001,
            "batch_size": 16,
            "epochs": 2,
            "patience": 2,
            "maximum_seconds": 30,
            "auxiliary_tasks": ["is_click"],
            "auxiliary_weights": {"is_click": 0.1},
        },
        "device": "cpu",
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    output = tmp_path / "output"

    receipt = train(tmp_path, config_path, output, max_batches=2)
    assert receipt["model_family"] == "deepfm"
    assert receipt["auxiliary_heads"] == ["is_click"]

    with np.load(tmp_path / "valid.npz", allow_pickle=False) as source:
        feature_only = {
            key: source[key]
            for key in ("X", "users", "videos", "date", "time_ms", "hourmin", "duration_ms")
        }
    feature_path = tmp_path / "feature_only.npz"
    np.savez_compressed(feature_path, **feature_only)
    predicted_path = tmp_path / "predicted.npy"
    prediction = predict(output / "checkpoint.pt", feature_path, predicted_path)

    assert prediction["model_family"] == "deepfm"
    assert np.load(predicted_path).shape == (64,)
    assert json.loads((output / "train_receipt.json").read_text(encoding="utf-8"))["parameters"] > 0


def test_history_state_can_attach_to_unlabelled_candidates() -> None:
    histories, masks = histories_from_state(np.asarray(["known", "new"]), {"known": [4, 5]}, 3)
    assert histories[0, masks[0]].tolist() == [4, 5]
    assert not masks[1].any()
