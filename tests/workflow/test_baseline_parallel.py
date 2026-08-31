from __future__ import annotations

from pathlib import Path
import json
from types import SimpleNamespace

import numpy as np

from flowstate.contract.challenge import load_challenge_contract
from flowstate.training.baseline import BaselineReproducer
from flowstate.contract.models import MetricReceipt


def test_parallel_official_fm_matches_sequential_results(tmp_path: Path) -> None:
    rng = np.random.default_rng(2026)
    train = {
        "X": rng.integers(0, 48, size=(128, 5), dtype=np.int64),
        "y": rng.integers(0, 2, size=128).astype(np.float32),
    }
    valid = {
        "X": rng.integers(0, 48, size=(48, 5), dtype=np.int64),
        "y": np.tile(np.asarray([0, 1, 0, 1], dtype=np.float32), 12),
        "users": np.repeat(np.arange(12), 4),
        "videos": np.arange(48),
    }
    np.savez(tmp_path / "train.npz", **train)
    np.savez(tmp_path / "valid.npz", **valid)

    contract = load_challenge_contract().model_copy(
        update={
            "baseline_config": {
                "k": 4,
                "lr": 0.001,
                "batch": 16,
                "max_epochs": 3,
                "patience": 2,
            }
        }
    )
    reproducer = BaselineReproducer(
        contract,
        Path("configs/baseline/official_fm.yaml"),
        tmp_path,
    )

    sequential = reproducer._fit_seeds(
        train, valid, tmp_path, tmp_path / "sequential", [0, 1, 2], workers=1
    )
    parallel = reproducer._fit_seeds(
        train, valid, tmp_path, tmp_path / "parallel", [0, 1, 2], workers=3
    )

    for expected, actual in zip(sequential, parallel):
        expected_seed, expected_model, expected_history = expected
        actual_seed, actual_model, actual_history = actual
        assert actual_seed == expected_seed
        assert actual_history == expected_history
        np.testing.assert_array_equal(actual_model.V, expected_model.V)
        np.testing.assert_array_equal(actual_model.W, expected_model.W)
        assert actual_model.b == expected_model.b


def test_label_shuffle_reads_organizer_scores_as_utf8_on_windows(tmp_path: Path) -> None:
    scores = tmp_path / "baseline_scores.json"
    scores.write_text(
        json.dumps(
            {
                "scores": {"random": {"valid": {"primary": 0.48}}},
                "note": "用真实标签当预测分得到的理论上限",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    receipt = MetricReceipt(
        receipt_id="m", run_id="sanity-label-shuffle",
        prediction_artifact_id="memory", evaluator_hash="e",
        config_hash="c", gauc=0.5, ndcg_at_5=0.45, primary=0.475,
        users=1, rows=2, comparable=False, scope="validation",
        receipt_hash="h",
    )
    reproducer = object.__new__(BaselineReproducer)
    reproducer.contract = SimpleNamespace(
        official_files={"baseline_scores": scores},
        baseline_config={"k": 1},
        sanity_shuffle_tolerance=0.02,
    )
    reproducer.config_path = scores
    reproducer._load_split = lambda _path: {
        "X": np.asarray([[0], [1]]),
        "y": np.asarray([0, 1]),
        "users": np.asarray(["u", "u"]),
    }
    model = SimpleNamespace(predict=lambda _features: np.asarray([0.1, 0.9]))
    reproducer._fit_one = lambda *_args, **_kwargs: (model, [])
    reproducer.evaluator = SimpleNamespace(score=lambda **_kwargs: receipt)

    result = reproducer.label_shuffle_control(tmp_path)

    assert result["bound"] == 0.5
    assert result["passed"] is True
