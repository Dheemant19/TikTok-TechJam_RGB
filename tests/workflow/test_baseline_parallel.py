from __future__ import annotations

from pathlib import Path

import numpy as np

from rigor_rs.contract.challenge import load_challenge_contract
from rigor_rs.training.baseline import BaselineReproducer


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
