from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from flowstate.cli.workflow import _data_artifact, _data_services
from flowstate.contract.challenge import load_challenge_contract, sha256_file
from flowstate.contract.models import TransformSpec
from flowstate.data.kuairand_1k import (
    KuaiRand1KPreprocessorService,
    KuaiRand1KProfilerService,
)


LOG_HEADER = [
    "user_id", "video_id", "date", "hourmin", "time_ms", "is_click",
    "is_like", "is_follow", "is_comment", "is_forward", "is_hate",
    "long_view", "play_time_ms", "duration_ms", "profile_stay_time",
    "comment_stay_time", "is_profile_enter", "is_rand", "tab",
]


def write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def fixture_data(root: Path) -> None:
    write_csv(
        root / "video_features_basic_1k.csv",
        ["video_id", "author_id"],
        [[10, 100], [20, 200], [30, 300]],
    )
    write_csv(root / "user_features_1k.csv", ["user_id"], [[1], [2]])
    write_csv(
        root / "log_standard_4_08_to_4_21_1k.csv",
        LOG_HEADER,
        [
            [1, 10, 20220408, 900, 1, 1, 0, 0, 0, 0, 0, 1, 800, 1000, 0, 0, 0, 0, 1],
            [1, 20, 20220409, 901, 2, 0, 0, 0, 0, 0, 0, 0, 100, 1200, 0, 0, 0, 0, 1],
            [2, 10, 20220410, 902, 3, 1, 1, 0, 0, 0, 0, 1, 900, 1000, 0, 0, 0, 0, 2],
        ],
    )
    write_csv(
        root / "log_standard_4_22_to_5_08_1k.csv",
        LOG_HEADER,
        [
            [1, 30, 20220422, 900, 4, 1, 0, 0, 0, 0, 0, 1, 700, 900, 0, 0, 0, 0, 1],
            [2, 20, 20220423, 901, 5, 0, 0, 0, 0, 0, 0, 0, 200, 1200, 0, 0, 0, 0, 2],
            [1, 10, 20220429, 902, 6, 0, 0, 0, 0, 0, 0, 0, 100, 1000, 0, 0, 0, 0, 1],
        ],
    )
    write_csv(root / "log_random_4_22_to_5_08_1k.csv", LOG_HEADER, [])


def test_kuairand_1k_contract_is_isolated_from_pure(monkeypatch) -> None:
    one_k = Path("KuaiRand-1K/data").resolve()
    monkeypatch.setenv("KUAIRAND_1K_DATA_DIR", str(one_k))
    contract = load_challenge_contract("configs/challenge/kuairand_1k.yaml")

    assert contract.benchmark == "kuairand_1k"
    assert contract.display_name == "KuaiRand-1K"
    assert contract.baseline_reference_mode == "reproduced"
    assert contract.dataset_files["train_log"].endswith("_1k.csv")
    assert contract.official_files["data_loader"].parent.name == "kuairand-1k-starter-kit"
    assert contract.official_files["evaluator"].name == "evaluate.py"
    assert contract.allow_test_labels_during_development is False
    assert contract.allow_test_score_command is False


def test_kuairand_1k_services_materialize_train_and_validation(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    fixture_data(data)
    monkeypatch.setenv("KUAIRAND_1K_DATA_DIR", str(data))
    contract = load_challenge_contract("configs/challenge/kuairand_1k.yaml")
    artifacts = tmp_path / "artifacts"
    profiler, preprocessor = _data_services(contract, artifacts)

    assert isinstance(profiler, KuaiRand1KProfilerService)
    assert isinstance(preprocessor, KuaiRand1KPreprocessorService)
    source = _data_artifact(contract)
    transform = preprocessor.fit_apply(source, TransformSpec())

    with np.load(transform.materializations["train"].path, allow_pickle=False) as train:
        assert train["X"].shape == (3, 5)
        assert train["y"].tolist() == [1.0, 0.0, 1.0]
        assert "is_click" in train.files
    with np.load(transform.materializations["valid"].path, allow_pickle=False) as valid:
        assert valid["X"].shape == (2, 5)
        assert valid["y"].tolist() == [1.0, 0.0]
        assert "is_click" not in valid.files


def test_kuairand_pure_contract_hashes_and_filenames_remain_unchanged() -> None:
    contract = load_challenge_contract("configs/challenge/kuairand_pure.yaml")

    assert contract.benchmark == "kuairand_pure"
    assert contract.dataset_files == {
        "train_log": "log_standard_4_08_to_4_21_pure.csv",
        "followup_log": "log_standard_4_22_to_5_08_pure.csv",
        "video_features": "video_features_basic_pure.csv",
        "user_features": "user_features_pure.csv",
        "randomized_exposure": "log_random_4_22_to_5_08_pure.csv",
    }
    for name, path in contract.official_files.items():
        assert sha256_file(path) == contract.official_hashes[name]
