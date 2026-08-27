from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from rigor_rs.contract.challenge import ChallengeContract, sha256_file
from rigor_rs.contract.models import (
    ArtifactRef, DataArtifact, ProfileConfig, ProfileReceipt, SplitTaint,
    TransformReceipt, TransformSpec,
)
from rigor_rs.ledger.workflow import canonical_hash, new_id


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _artifact(path: Path, media_type: str, *, taint: SplitTaint | None = None, rows: int | None = None, parents: list[str] | None = None) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=new_id("artifact"), path=path, content_hash=sha256_file(path), media_type=media_type,
        taint=taint, row_count=rows, parent_ids=parents or [],
    )


class ProfilerService:
    def __init__(self, contract: ChallengeContract, artifact_root: Path) -> None:
        self.contract = contract
        self.artifact_root = artifact_root

    def _logs(self) -> pl.LazyFrame:
        files = [
            self.contract.dataset_dir / "log_standard_4_08_to_4_21_pure.csv",
            self.contract.dataset_dir / "log_standard_4_22_to_5_08_pure.csv",
        ]
        columns = [
            "date", "user_id", "video_id", "long_view", "play_time_ms", "duration_ms", "tab",
            "is_click", "is_like", "is_follow", "is_comment", "is_forward",
        ]
        frames = []
        for file in files:
            frame = pl.scan_csv(file, infer_schema_length=1000, ignore_errors=True)
            available = [name for name in columns if name in frame.collect_schema().names()]
            frames.append(frame.select(available))
        return pl.concat(frames, how="diagonal_relaxed")

    def profile(self, artifact: DataArtifact, config: ProfileConfig) -> ProfileReceipt:
        cache_key = canonical_hash({
            "source": artifact.source_hash, "code": artifact.code_hash,
            "config": config.model_dump(mode="json"), "contract_hashes": self.contract.official_hashes,
        })
        output = self.artifact_root / "profiles" / cache_key
        profile_path = output / "profile.json"
        visual_path = output / "visualization.json"
        if profile_path.is_file() and visual_path.is_file():
            return ProfileReceipt(
                receipt_id=new_id("profile"), profile=_artifact(profile_path, "application/json"),
                visualization=_artifact(visual_path, "application/json"), input_hash=cache_key, cache_hit=True,
            )
        started = time.perf_counter()
        frame = self._logs()
        split_expr = (
            pl.when(pl.col("date").is_between(*self.contract.splits["train"])).then(pl.lit("train"))
            .when(pl.col("date").is_between(*self.contract.splits["valid"])).then(pl.lit("valid"))
            .otherwise(pl.lit("excluded")).alias("split")
        )
        dev = frame.with_columns(split_expr).filter(pl.col("split") != "excluded")
        split_stats = dev.group_by("split").agg(
            pl.len().alias("rows"), pl.col("user_id").n_unique().alias("users"),
            pl.col("video_id").n_unique().alias("videos"), pl.col("long_view").cast(pl.Float64).mean().alias("long_view_rate"),
        ).collect().to_dicts()
        user_labels = dev.group_by(["split", "user_id"]).agg(
            pl.len().alias("exposures"), pl.col("long_view").cast(pl.Int64).sum().alias("positives")
        ).with_columns(
            pl.when(pl.col("positives") == 0).then(pl.lit("all_negative"))
            .when(pl.col("positives") == pl.col("exposures")).then(pl.lit("all_positive"))
            .otherwise(pl.lit("mixed")).alias("label_group")
        )
        label_groups = user_labels.group_by(["split", "label_group"]).agg(pl.len().alias("users")).collect().to_dicts()
        interaction_summary = user_labels.group_by("split").agg(
            pl.col("exposures").min().alias("min"), pl.col("exposures").median().alias("median"),
            pl.col("exposures").mean().alias("mean"), pl.col("exposures").quantile(0.95).alias("p95"),
            pl.col("exposures").max().alias("max"),
        ).collect().to_dicts()
        schema = dev.collect_schema()
        missing_expr = [pl.col(name).null_count().alias(name) for name in schema.names()]
        missing = dev.select(missing_expr).collect().to_dicts()[0]
        cardinalities = dev.select([
            pl.col(name).n_unique().alias(name) for name in schema.names()
            if name not in {"play_time_ms", "duration_ms"}
        ]).collect().to_dicts()[0]
        duplicate_rate = dev.select(
            (1 - pl.struct(["user_id", "video_id", "date"]).n_unique() / pl.len()).alias("duplicate_exposure_rate")
        ).collect().item()
        censoring = dev.select(
            pl.len().alias("rows"),
            (pl.col("play_time_ms").cast(pl.Float64) >= pl.col("duration_ms").cast(pl.Float64)).sum().alias("completed_or_censored"),
            (pl.col("play_time_ms").cast(pl.Float64) / pl.col("duration_ms").cast(pl.Float64).clip(1, None)).median().alias("median_watch_fraction"),
        ).collect().to_dicts()[0]
        daily = dev.group_by(["split", "date"]).agg(
            pl.len().alias("rows"), pl.col("long_view").cast(pl.Float64).mean().alias("long_view_rate")
        ).sort(["split", "date"]).collect().to_dicts()
        aux = [name for name in ("is_click", "is_like", "is_follow", "is_comment", "is_forward", "play_time_ms") if name in schema.names()]
        correlations = {}
        for name in aux:
            value = dev.select(pl.corr(pl.col(name).cast(pl.Float64), pl.col("long_view").cast(pl.Float64))).collect().item()
            correlations[name] = None if value is None or not math.isfinite(float(value)) else float(value)
        profile = {
            "schema_version": 1, "input_artifact_id": artifact.artifact_id, "split_stats": split_stats,
            "label_groups": label_groups, "interactions_per_user": interaction_summary,
            "missing_by_field": missing, "cardinalities": cardinalities,
            "duplicate_exposure_rate": duplicate_rate, "watch_time_censoring": censoring,
            "temporal_drift": daily, "auxiliary_label_correlations": correlations,
            "source_hash": artifact.source_hash, "elapsed_seconds": time.perf_counter() - started,
            "warnings": [],
        }
        visualization = {
            "schema_version": 1,
            "split_overview": split_stats,
            "user_label_groups": label_groups,
            "sequence_lengths": interaction_summary,
            "missing_fields": [{"field": key, "count": value} for key, value in missing.items()],
            "cardinality": [{"field": key, "count": value} for key, value in cardinalities.items()],
            "daily_drift": daily,
            "watch_time": censoring,
            "duplicate_exposure_rate": duplicate_rate,
            "tables": {"daily_drift": daily, "split_overview": split_stats},
        }
        _atomic_json(profile_path, profile)
        _atomic_json(visual_path, visualization)
        return ProfileReceipt(
            receipt_id=new_id("profile"), profile=_artifact(profile_path, "application/json"),
            visualization=_artifact(visual_path, "application/json"), input_hash=cache_key, cache_hit=False,
            warnings=profile["warnings"],
        )


class PreprocessorService:
    def __init__(self, contract: ChallengeContract, artifact_root: Path) -> None:
        self.contract = contract
        self.artifact_root = artifact_root

    def _load_dev_rows(self) -> dict[str, list[tuple[Any, ...]]]:
        video = pl.read_csv(self.contract.dataset_dir / "video_features_basic_pure.csv", columns=["video_id", "author_id"])
        author = dict(zip(video["video_id"].cast(pl.String).to_list(), video["author_id"].cast(pl.String).to_list()))
        output: dict[str, list[tuple[Any, ...]]] = {"train": [], "valid": []}
        files = [
            self.contract.dataset_dir / "log_standard_4_08_to_4_21_pure.csv",
            self.contract.dataset_dir / "log_standard_4_22_to_5_08_pure.csv",
        ]
        for file in files:
            table = pl.read_csv(file, columns=["date", "user_id", "video_id", "tab", "duration_ms", "long_view"])
            for split in ("train", "valid"):
                lo, hi = self.contract.splits[split]
                rows = table.filter(pl.col("date").is_between(lo, hi)).iter_rows(named=True)
                output[split].extend((
                    int(row["date"]), str(row["user_id"]), str(row["video_id"]),
                    author.get(str(row["video_id"]), "UNK"), str(row["tab"]),
                    float(row["duration_ms"]), 1 if str(row["long_view"]) != "0" else 0,
                ) for row in rows)
        return output

    def fit_apply(self, source: DataArtifact, spec: TransformSpec) -> TransformReceipt:
        key = canonical_hash({"source": source.source_hash, "code": source.code_hash, "spec": spec.model_dump(mode="json")})
        output = self.artifact_root / "transforms" / key
        receipt_path = output / "transform_receipt.json"
        if receipt_path.is_file():
            document = json.loads(receipt_path.read_text(encoding="utf-8"))
            return TransformReceipt(
                receipt_id=new_id("transform"),
                state=_artifact(output / "transform_state.json", "application/json"),
                spec=_artifact(output / "transform_spec.json", "application/json"),
                receipt=_artifact(receipt_path, "application/json"),
                materializations={name: _artifact(output / f"{name}.npz", "application/octet-stream", rows=value["rows"]) for name, value in document["splits"].items()},
                cache_hit=True,
            )
        rows = self._load_dev_rows()
        train = rows["train"]
        edges = np.quantile(np.asarray([row[5] for row in train]), np.linspace(0, 1, spec.duration_quantiles + 1)[1:-1])
        def raw(row: tuple[Any, ...]) -> list[str]:
            return [row[1], row[2], row[3], row[4], str(int(np.searchsorted(edges, row[5])))]
        vocabs: list[dict[str, int]] = [dict() for _ in spec.fields]
        for row in train:
            for index, value in enumerate(raw(row)):
                if value not in vocabs[index]:
                    vocabs[index][value] = len(vocabs[index])
        unknown = [len(vocab) for vocab in vocabs]
        field_dims = [len(vocab) + 1 for vocab in vocabs]
        offsets = np.cumsum([0, *field_dims[:-1]]).astype(np.int32)
        output.mkdir(parents=True, exist_ok=True)
        state = {
            "schema_version": 1, "fields": spec.fields, "vocabularies": vocabs, "unknown_ids": unknown,
            "duration_bucket_edges": edges.tolist(), "field_dims": field_dims, "offsets": offsets.tolist(),
            "source_hash": source.source_hash, "code_hash": source.code_hash, "seed": spec.seed,
            "fit_split": "train",
        }
        _atomic_json(output / "transform_spec.json", spec.model_dump(mode="json"))
        _atomic_json(output / "transform_state.json", state)
        split_receipts: dict[str, dict[str, Any]] = {}
        for split, values in rows.items():
            features = np.empty((len(values), len(spec.fields)), dtype=np.int32)
            labels = np.empty(len(values), dtype=np.float32)
            users = np.empty(len(values), dtype="<U128")
            videos = np.empty(len(values), dtype="<U128")
            for row_index, row in enumerate(values):
                for field_index, value in enumerate(raw(row)):
                    features[row_index, field_index] = vocabs[field_index].get(value, unknown[field_index]) + offsets[field_index]
                labels[row_index] = row[6]
                users[row_index], videos[row_index] = row[1], row[2]
            path = output / f"{split}.npz"
            np.savez_compressed(path, X=features, y=labels, users=users, videos=videos)
            if not np.isfinite(features).all() or not np.isfinite(labels).all():
                raise ValueError(f"non-finite values in {split} transform")
            split_receipts[split] = {
                "rows": len(values), "schema": ["X", "y", "users", "videos"],
                "content_hash": sha256_file(path), "taints": [f"{split.upper()}_FEATURES", f"{split.upper()}_LABELS"],
                "unknown_counts": [int(np.sum(features[:, i] == unknown[i] + offsets[i])) for i in range(len(spec.fields))],
            }
        receipt = {
            "schema_version": 1, "receipt_id": new_id("transform"), "source_hash": source.source_hash,
            "transform_state_hash": sha256_file(output / "transform_state.json"), "splits": split_receipts,
            "join_expansion_ratio": 1.0, "row_order_preserved": True,
        }
        _atomic_json(receipt_path, receipt)
        return TransformReceipt(
            receipt_id=receipt["receipt_id"], state=_artifact(output / "transform_state.json", "application/json"),
            spec=_artifact(output / "transform_spec.json", "application/json"),
            receipt=_artifact(receipt_path, "application/json"),
            materializations={name: _artifact(output / f"{name}.npz", "application/octet-stream", rows=detail["rows"], parents=[source.artifact_id]) for name, detail in split_receipts.items()},
            cache_hit=False,
        )
