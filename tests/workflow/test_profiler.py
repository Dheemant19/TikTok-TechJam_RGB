from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from rigor_rs.contract.challenge import load_challenge_contract
from rigor_rs.contract.models import DataArtifact, ProfileConfig, SplitTaint, TransformSpec
from rigor_rs.data.profiler import PreprocessorService, ProfilerService


LOG_HEADER = [
    "date", "user_id", "video_id", "long_view", "play_time_ms", "duration_ms", "tab",
    "is_click", "is_like", "is_follow", "is_comment", "is_forward",
    "time_ms", "hourmin", "is_hate",
]


def write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle); writer.writerow(header); writer.writerows(rows)


def test_profile_and_validation_only_unknown_mapping(tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_csv(data / "video_features_basic_pure.csv", ["video_id", "author_id"], [["v1", "a1"], ["v2", "a2"]])
    write_csv(data / "user_features_pure.csv", ["user_id"], [["u1"], ["u2"]])
    write_csv(data / "log_standard_4_08_to_4_21_pure.csv", LOG_HEADER, [
        [20220408, "u1", "v1", 1, 900, 1000, "1", 1, 0, 0, 0, 0, 1649400000000, 1200, 0],
        [20220409, "u1", "v1", 0, 100, 1000, "1", 0, 0, 0, 0, 0, 1649486400000, 1300, 0],
    ])
    write_csv(data / "log_standard_4_22_to_5_08_pure.csv", LOG_HEADER, [
        [20220422, "u2", "v2", 1, 800, 1000, "2", 1, 0, 0, 0, 0, 1650585600000, 1400, 0],
    ])
    contract = load_challenge_contract().model_copy(update={"dataset_dir": data})
    artifact = DataArtifact(
        artifact_id="data", path=data,
        taints={SplitTaint.TRAIN_FEATURES, SplitTaint.TRAIN_LABELS, SplitTaint.VALIDATION_FEATURES},
        row_count=3, schema_fingerprint="fixture", source_hash="source", code_hash="code",
        creation_receipt_id="receipt",
    )
    profile = ProfilerService(contract, tmp_path / "artifacts").profile(artifact, ProfileConfig())
    assert json.loads(profile.profile.path.read_text())["split_stats"]
    transform = PreprocessorService(contract, tmp_path / "artifacts").fit_apply(artifact, TransformSpec())
    state = json.loads(transform.state.path.read_text())
    assert "u2" not in state["vocabularies"][0]
    with np.load(transform.materializations["valid"].path, allow_pickle=False) as valid:
        expected_unknown = state["unknown_ids"][0] + state["offsets"][0]
        assert int(valid["X"][0, 0]) == expected_unknown
        assert valid["users"].tolist() == ["u2"]
    with np.load(transform.materializations["train"].path, allow_pickle=False) as train:
        assert {"date", "time_ms", "hourmin", "duration_ms", "play_time_ms", "is_click"} <= set(train.files)
    with np.load(transform.materializations["valid"].path, allow_pickle=False) as valid:
        assert {"date", "time_ms", "hourmin", "duration_ms"} <= set(valid.files)
        assert "play_time_ms" not in valid.files
