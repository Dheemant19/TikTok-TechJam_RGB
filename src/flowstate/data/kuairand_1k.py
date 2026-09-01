from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from flowstate.contract.models import DataArtifact, TransformReceipt, TransformSpec
from flowstate.data.profiler import (
    PreprocessorService,
    ProfilerService,
    _artifact,
    _atomic_json,
)
from flowstate.ledger.workflow import canonical_hash, new_id


class KuaiRand1KProfilerService(ProfilerService):
    """Profile KuaiRand-1K without changing the KuaiRand-Pure profiler."""

    def _logs(self) -> pl.LazyFrame:
        files = [
            *self.contract.log_paths("train"),
            *self.contract.log_paths("followup"),
        ]
        columns = [
            "date", "user_id", "video_id", "long_view", "play_time_ms",
            "duration_ms", "tab", "is_click", "is_like", "is_follow",
            "is_comment", "is_forward",
        ]
        frames = []
        for file in files:
            frame = pl.scan_csv(file, infer_schema_length=1000, ignore_errors=True)
            available = [name for name in columns if name in frame.collect_schema().names()]
            frames.append(frame.select(available))
        return pl.concat(frames, how="diagonal_relaxed")


class KuaiRand1KPreprocessorService(PreprocessorService):
    """Memory-bounded 1K preprocessing using columnar frames instead of row tuples."""

    _COLUMNS = [
        "date", "user_id", "video_id", "tab", "duration_ms", "long_view",
        "time_ms", "hourmin", "play_time_ms", "is_click", "is_like",
        "is_follow", "is_comment", "is_forward", "is_hate",
    ]

    def _split_table(self, split: str, video: pl.DataFrame) -> pl.DataFrame:
        lo, hi = self.contract.splits[split]
        filename = (
            self.contract.dataset_files["train_log"]
            if split == "train"
            else self.contract.dataset_files["followup_log"]
        )
        return (
            pl.scan_csv(
                self.contract.dataset_dir / filename,
                infer_schema_length=1000,
                ignore_errors=False,
            )
            .select(self._COLUMNS)
            .filter(pl.col("date").is_between(lo, hi))
            .collect(engine="streaming")
            .join(video, on="video_id", how="left")
            .with_columns(
                pl.col("author_id").cast(pl.String).fill_null("UNK"),
                pl.col("user_id").cast(pl.String),
                pl.col("video_id").cast(pl.String),
                pl.col("tab").cast(pl.String),
            )
        )

    @staticmethod
    def _field_series(table: pl.DataFrame, edges: np.ndarray) -> list[pl.Series]:
        duration_bucket = pl.Series(
            "dur_bucket",
            np.searchsorted(edges, table["duration_ms"].cast(pl.Float64).to_numpy()),
        ).cast(pl.String)
        return [
            table["user_id"],
            table["video_id"],
            table["author_id"],
            table["tab"],
            duration_bucket,
        ]

    @staticmethod
    def _encode_field(series: pl.Series, vocabulary: dict[str, int], unknown: int) -> np.ndarray:
        return (
            series.cast(pl.String)
            .replace_strict(vocabulary, default=unknown, return_dtype=pl.Int32)
            .to_numpy()
        )

    def fit_apply(self, source: DataArtifact, spec: TransformSpec) -> TransformReceipt:
        key = canonical_hash({
            "source": source.source_hash,
            "code": source.code_hash,
            "spec": spec.model_dump(mode="json"),
            "contract_hashes": self.contract.official_hashes,
        })
        output = self.artifact_root / "transforms" / key
        receipt_path = output / "transform_receipt.json"
        if receipt_path.is_file():
            document = json.loads(receipt_path.read_text(encoding="utf-8"))
            return TransformReceipt(
                receipt_id=new_id("transform"),
                state=_artifact(output / "transform_state.json", "application/json"),
                spec=_artifact(output / "transform_spec.json", "application/json"),
                receipt=_artifact(receipt_path, "application/json"),
                materializations={
                    name: _artifact(
                        output / f"{name}.npz",
                        "application/octet-stream",
                        rows=value["rows"],
                    )
                    for name, value in document["splits"].items()
                },
                cache_hit=True,
            )

        video = (
            pl.scan_csv(
                self.contract.dataset_dir / self.contract.dataset_files["video_features"],
                infer_schema_length=1000,
            )
            .select("video_id", "author_id")
            .collect(engine="streaming")
        )
        tables = {
            split: self._split_table(split, video)
            for split in ("train", "valid")
        }
        train = tables["train"]
        edges = np.quantile(
            train["duration_ms"].cast(pl.Float64).to_numpy(),
            np.linspace(0, 1, spec.duration_quantiles + 1)[1:-1],
        )
        train_fields = self._field_series(train, edges)
        vocabularies: list[dict[str, int]] = []
        for series in train_fields:
            values = series.unique(maintain_order=True).to_list()
            vocabularies.append({str(value): index for index, value in enumerate(values)})
        unknown = [len(vocabulary) for vocabulary in vocabularies]
        field_dims = [len(vocabulary) + 1 for vocabulary in vocabularies]
        offsets = np.cumsum([0, *field_dims[:-1]]).astype(np.int32)

        output.mkdir(parents=True, exist_ok=False)
        state = {
            "schema_version": 1,
            "fields": spec.fields,
            "vocabularies": vocabularies,
            "unknown_ids": unknown,
            "duration_bucket_edges": edges.tolist(),
            "field_dims": field_dims,
            "offsets": offsets.tolist(),
            "source_hash": source.source_hash,
            "code_hash": source.code_hash,
            "seed": spec.seed,
            "fit_split": "train",
        }
        _atomic_json(output / "transform_spec.json", spec.model_dump(mode="json"))
        _atomic_json(output / "transform_state.json", state)

        split_receipts: dict[str, dict[str, Any]] = {}
        for split, table in tables.items():
            fields = self._field_series(table, edges)
            features = np.column_stack([
                self._encode_field(series, vocabularies[index], unknown[index]) + offsets[index]
                for index, series in enumerate(fields)
            ]).astype(np.int32, copy=False)
            arrays: dict[str, np.ndarray] = {
                "X": features,
                "y": table["long_view"].cast(pl.Float32).to_numpy(),
                "users": table["user_id"].cast(pl.Int64).to_numpy(),
                "videos": table["video_id"].cast(pl.Int64).to_numpy(),
                "date": table["date"].cast(pl.Int32).to_numpy(),
                "time_ms": table["time_ms"].cast(pl.Int64).to_numpy(),
                "hourmin": table["hourmin"].cast(pl.Int16).to_numpy(),
                "duration_ms": table["duration_ms"].cast(pl.Float32).to_numpy(),
            }
            if split == "train":
                arrays.update({
                    "play_time_ms": table["play_time_ms"].cast(pl.Float32).to_numpy(),
                    "is_click": table["is_click"].cast(pl.Int8).to_numpy(),
                    "is_like": table["is_like"].cast(pl.Int8).to_numpy(),
                    "is_follow": table["is_follow"].cast(pl.Int8).to_numpy(),
                    "is_comment": table["is_comment"].cast(pl.Int8).to_numpy(),
                    "is_forward": table["is_forward"].cast(pl.Int8).to_numpy(),
                    "is_hate": table["is_hate"].cast(pl.Int8).to_numpy(),
                })
            path = output / f"{split}.npz"
            np.savez_compressed(path, **arrays)
            if not all(
                np.isfinite(value).all()
                for value in arrays.values()
                if value.dtype.kind not in {"U", "S", "O"}
            ):
                raise ValueError(f"non-finite values in {split} transform")
            split_receipts[split] = {
                "rows": len(table),
                "schema": list(arrays),
                "content_hash": _artifact(path, "application/octet-stream").content_hash,
                "taints": [
                    f"{'TRAIN' if split == 'train' else 'VALIDATION'}_FEATURES",
                    f"{'TRAIN' if split == 'train' else 'VALIDATION'}_LABELS",
                ],
                "unknown_counts": [
                    int(np.sum(features[:, index] == unknown[index] + offsets[index]))
                    for index in range(len(spec.fields))
                ],
            }

        receipt = {
            "schema_version": 1,
            "receipt_id": new_id("transform"),
            "source_hash": source.source_hash,
            "transform_state_hash": _artifact(
                output / "transform_state.json", "application/json"
            ).content_hash,
            "splits": split_receipts,
            "join_expansion_ratio": 1.0,
            "row_order_preserved": True,
        }
        _atomic_json(receipt_path, receipt)
        return TransformReceipt(
            receipt_id=receipt["receipt_id"],
            state=_artifact(output / "transform_state.json", "application/json"),
            spec=_artifact(output / "transform_spec.json", "application/json"),
            receipt=_artifact(receipt_path, "application/json"),
            materializations={
                name: _artifact(
                    output / f"{name}.npz",
                    "application/octet-stream",
                    rows=detail["rows"],
                    parents=[source.artifact_id],
                )
                for name, detail in split_receipts.items()
            },
            cache_hit=False,
        )
