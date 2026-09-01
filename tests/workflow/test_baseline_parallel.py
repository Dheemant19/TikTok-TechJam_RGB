from __future__ import annotations

from pathlib import Path
import json
from types import SimpleNamespace

import numpy as np
import pytest
import torch


from flowstate.contract.challenge import load_challenge_contract
from flowstate.training.baseline import (
    BaselineReproducer,
    _TorchOfficialFM,
    _load_fm_class,
    _resolve_execution_device,
    _is_accelerator_failure,
)
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


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is unavailable")
def test_torch_cuda_official_fm_preserves_numpy_predictions() -> None:
    rng = np.random.default_rng(2026)
    features = rng.integers(0, 96, size=(256, 5), dtype=np.int64)
    labels = rng.integers(0, 2, size=256).astype(np.float32)
    fm_class = _load_fm_class(Path("kuairand-starter-kit/baseline.py"))
    numpy_model = fm_class(96, k=8, lr=0.001, seed=7)
    cuda_model = _TorchOfficialFM(fm_class(96, k=8, lr=0.001, seed=7), "cuda")

    for start in range(0, len(labels), 32):
        batch = slice(start, start + 32)
        numpy_model.step(features[batch], labels[batch])
        cuda_model.step(features[batch], labels[batch])

    cuda_model.finalize()
    np.testing.assert_allclose(
        cuda_model.predict(features),
        numpy_model.predict(features),
        rtol=2e-4,
        atol=2e-5,
    )


def test_auto_baseline_uses_torch_cpu_without_a_gpu(monkeypatch) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)

    assert _resolve_execution_device("auto") == "torch_cpu"


def test_auto_baseline_uses_apple_mps_when_available(monkeypatch) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)

    assert _resolve_execution_device("auto") == "mps"


def test_torch_cpu_official_fm_preserves_numpy_predictions() -> None:
    rng = np.random.default_rng(2027)
    features = rng.integers(0, 96, size=(128, 5), dtype=np.int64)
    labels = rng.integers(0, 2, size=128).astype(np.float32)
    fm_class = _load_fm_class(Path("kuairand-starter-kit/baseline.py"))
    numpy_model = fm_class(96, k=8, lr=0.001, seed=8)
    torch_model = _TorchOfficialFM(
        fm_class(96, k=8, lr=0.001, seed=8), "torch_cpu"
    )

    for start in range(0, len(labels), 32):
        batch = slice(start, start + 32)
        numpy_model.step(features[batch], labels[batch])
        torch_model.step(features[batch], labels[batch])

    torch_model.finalize()
    np.testing.assert_allclose(
        torch_model.predict(features),
        numpy_model.predict(features),
        rtol=2e-4,
        atol=2e-5,
    )


def test_auto_accelerator_failure_retries_on_torch_cpu(tmp_path: Path) -> None:
    reproducer = object.__new__(BaselineReproducer)
    reproducer.requested_execution_device = "auto"
    reproducer.execution_device = "cuda"
    calls: list[str] = []

    def fit(*_args, **_kwargs):
        calls.append(reproducer.execution_device)
        if len(calls) == 1:
            raise RuntimeError("CUDA out of memory")
        return ["cpu-result"]

    reproducer._fit_seeds = fit
    fitted, recovery = reproducer._fit_seeds_with_fallback(
        {}, {}, tmp_path, tmp_path, [0], 1
    )

    assert fitted == ["cpu-result"]
    assert calls == ["cuda", "torch_cpu"]
    assert reproducer.execution_device == "torch_cpu"
    assert recovery is not None
    assert recovery["result"] == "recovered"
    assert (tmp_path / "device_fallback.json").is_file()


def test_cpu_failures_are_not_misreported_as_accelerator_failures() -> None:
    assert not _is_accelerator_failure(RuntimeError("bad schema"), "torch_cpu")
