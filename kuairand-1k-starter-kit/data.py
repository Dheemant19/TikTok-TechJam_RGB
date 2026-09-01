"""KuaiRand-1K loading, date splits, and five-field FM encoding.

This adapter mirrors the KuaiRand-Pure task contract without modifying the
organizer-provided Pure starter kit.
"""
from __future__ import annotations

import csv
import os
from collections.abc import Iterator

import numpy as np

LABEL = "long_view"
SPLITS = {
    "train": (20220408, 20220421),
    "valid": (20220422, 20220428),
    "test": (20220429, 20220508),
}
FIELDS = ["user_id", "video_id", "author_id", "tab", "dur_bucket"]

TRAIN_LOG = "log_standard_4_08_to_4_21_1k.csv"
FOLLOWUP_LOG = "log_standard_4_22_to_5_08_1k.csv"
VIDEO_FEATURES = "video_features_basic_1k.csv"


def iter_evaluation_rows(data_dir: str, split: str) -> Iterator[tuple[str, str, int]]:
    """Yield user, video, and label in deterministic evaluation row order."""
    if split not in {"valid", "test"}:
        raise ValueError("evaluation split must be 'valid' or 'test'")
    lo, hi = SPLITS[split]
    with open(os.path.join(data_dir, FOLLOWUP_LOG), newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            date = int(row["date"])
            if lo <= date <= hi:
                yield row["user_id"], row["video_id"], 1 if row[LABEL] != "0" else 0


def load(data_dir: str) -> dict[str, list[tuple[int, str, str, str, str, float, int]]]:
    """Load the complete benchmark into the tuple format used by the FM reference."""
    video_to_author: dict[str, str] = {}
    with open(os.path.join(data_dir, VIDEO_FEATURES), newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            video_to_author[row["video_id"]] = row["author_id"]

    output: dict[str, list[tuple[int, str, str, str, str, float, int]]] = {
        name: [] for name in SPLITS
    }
    for filename in (TRAIN_LOG, FOLLOWUP_LOG):
        with open(os.path.join(data_dir, filename), newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                date = int(row["date"])
                for split, (lo, hi) in SPLITS.items():
                    if lo <= date <= hi:
                        output[split].append(
                            (
                                date,
                                row["user_id"],
                                row["video_id"],
                                video_to_author.get(row["video_id"], "UNK"),
                                row["tab"],
                                float(row["duration_ms"]),
                                1 if row[LABEL] != "0" else 0,
                            )
                        )
                        break
    return output


def _bucket_edges(durations: list[float], n: int = 10) -> np.ndarray:
    return np.quantile(np.asarray(durations), np.linspace(0, 1, n + 1)[1:-1])


def encode(splits):
    """Encode train-fitted categorical values with one unknown slot per field."""
    train = splits["train"]
    edges = _bucket_edges([row[5] for row in train])

    def raw(row):
        return [
            row[1], row[2], row[3], row[4],
            str(int(np.searchsorted(edges, row[5]))),
        ]

    vocabularies = [dict() for _ in FIELDS]
    for row in train:
        for index, value in enumerate(raw(row)):
            if value not in vocabularies[index]:
                vocabularies[index][value] = len(vocabularies[index])
    unknown = [len(vocabulary) for vocabulary in vocabularies]
    field_dims = [len(vocabulary) + 1 for vocabulary in vocabularies]
    offsets = np.cumsum([0, *field_dims[:-1]]).astype(np.int32)

    encoded = {}
    for split, rows in splits.items():
        features = np.empty((len(rows), len(FIELDS)), dtype=np.int32)
        labels = np.empty(len(rows), dtype=np.float32)
        users = []
        for row_index, row in enumerate(rows):
            for field_index, value in enumerate(raw(row)):
                features[row_index, field_index] = (
                    vocabularies[field_index].get(value, unknown[field_index])
                    + offsets[field_index]
                )
            labels[row_index] = row[6]
            users.append(row[1])
        encoded[split] = (features, labels, users)
    return encoded, int(sum(field_dims))
