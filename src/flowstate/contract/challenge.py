from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from flowstate.knowledge.config import repository_root


class ChallengeContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    benchmark: str
    dataset_dir: Path
    display_name: str = "KuaiRand-Pure"
    label: str
    splits: dict[str, tuple[int, int]]
    fields: list[str]
    metrics: list[str]
    primary_rule: str
    baseline_valid: dict[str, float]
    baseline_test: dict[str, float]
    baseline_config: dict[str, Any]
    baseline_seed_std: float
    convergence_epsilon: float
    convergence_patience: int
    submission_header: list[str]
    sanity_shuffle_tolerance: float
    official_files: dict[str, Path]
    official_hashes: dict[str, str]
    dataset_files: dict[str, str] = Field(default_factory=lambda: {
        "train_log": "log_standard_4_08_to_4_21_pure.csv",
        "followup_log": "log_standard_4_22_to_5_08_pure.csv",
        "video_features": "video_features_basic_pure.csv",
        "user_features": "user_features_pure.csv",
        "randomized_exposure": "log_random_4_22_to_5_08_pure.csv",
    })
    baseline_reference_mode: str = "published"
    baseline_display_name: str = "Official FM baseline"
    baseline_runtime_config: Path = Path("configs/baseline/official_fm.yaml")
    allow_test_labels_during_development: bool = False
    allow_test_score_command: bool = False

    def log_paths(self, phase: str) -> list[Path]:
        if phase not in {"train", "followup"}:
            raise ValueError(f"unsupported log phase: {phase}")
        base = f"{phase}_log"
        names = [
            value
            for key, value in sorted(self.dataset_files.items())
            if key == base or key.startswith(f"{base}_part")
        ]
        if not names:
            raise ValueError(f"dataset contract has no {phase} logs")
        return [self.dataset_dir / name for name in names]

    def verify_hashes(self) -> None:
        changed = [name for name, path in self.official_files.items() if sha256_file(path) != self.official_hashes[name]]
        if changed:
            raise RuntimeError(f"official challenge files changed after session start: {', '.join(changed)}")

    def public_summary(self) -> dict[str, Any]:
        return {
            "benchmark": self.benchmark, "display_name": self.display_name,
            "label": self.label, "splits": self.splits,
            "fields": self.fields, "metrics": self.metrics, "primary_rule": self.primary_rule,
            "convergence_epsilon": self.convergence_epsilon,
            "convergence_patience": self.convergence_patience,
            "submission_header": self.submission_header,
            "baseline_reference_mode": self.baseline_reference_mode,
            "baseline_display_name": self.baseline_display_name,
            "official_hashes": self.official_hashes,
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _literal_assignments(path: Path, names: set[str]) -> dict[str, Any]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, Any] = {}
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    found[target.id] = ast.literal_eval(node.value)
    missing = names - found.keys()
    if missing:
        raise ValueError(f"official file {path} is missing constants: {sorted(missing)}")
    return found


def _load_bonus_contract(
    root: Path,
    config: dict[str, Any],
) -> ChallengeContract:
    benchmark = str(config["benchmark"])
    display_name = str(config.get("display_name", benchmark))
    dataset_config = config["dataset"]
    env_name = "KUAIRAND_1K_DATA_DIR"
    template = str(dataset_config["directory"])
    if template != f"${{{env_name}}}":
        raise ValueError(f"{display_name} dataset path must come from {env_name}")
    dataset_value = os.getenv(env_name) or dataset_config.get("default_directory")
    if not dataset_value:
        raise ValueError(f"{env_name} is required")
    dataset_dir = Path(dataset_value)
    if not dataset_dir.is_absolute():
        dataset_dir = root / dataset_dir

    dataset_files = {str(name): str(value) for name, value in dataset_config["files"].items()}
    required_keys = {"train_log", "followup_log", "video_features", "user_features"}
    missing_keys = sorted(required_keys - dataset_files.keys())
    if missing_keys:
        raise ValueError(f"{display_name} config is missing dataset file keys: {missing_keys}")
    missing_data = [
        name
        for name in sorted(dataset_files.values())
        if not (dataset_dir / name).is_file()
    ]
    if missing_data:
        raise FileNotFoundError(f"missing {display_name} files: {missing_data}")

    official = {name: root / value for name, value in config["official_files"].items()}
    missing_files = [str(item) for item in official.values() if not item.is_file()]
    if missing_files:
        raise FileNotFoundError(f"missing {display_name} contract files: {missing_files}")
    data_constants = _literal_assignments(
        official["data_loader"],
        {"LABEL", "SPLITS", "FIELDS"},
    )
    submit_constants = _literal_assignments(official["submission_checker"], {"HEADER"})
    scores = json.loads(official["baseline_scores"].read_text(encoding="utf-8"))
    fm = scores["scores"]["fm_reference"]
    runtime_config = root / config["baseline"]["runtime_config"]
    if not runtime_config.is_file():
        raise FileNotFoundError(f"missing {display_name} baseline config: {runtime_config}")
    return ChallengeContract(
        benchmark=benchmark,
        display_name=display_name,
        dataset_dir=dataset_dir.resolve(),
        label=data_constants["LABEL"],
        splits={name: tuple(values) for name, values in data_constants["SPLITS"].items()},
        fields=list(data_constants["FIELDS"]),
        metrics=list(scores["metrics"]),
        primary_rule=str(scores["primary"]),
        baseline_valid={},
        baseline_test={},
        baseline_config=fm["config"],
        baseline_seed_std=0.0,
        convergence_epsilon=float(scores["convergence_rule"]["epsilon"]),
        convergence_patience=int(scores["convergence_rule"]["N"]),
        submission_header=submit_constants["HEADER"],
        sanity_shuffle_tolerance=float(config["integrity"]["sanity_shuffle_tolerance"]),
        official_files=official,
        official_hashes={name: sha256_file(file) for name, file in official.items()},
        dataset_files=dataset_files,
        baseline_reference_mode="reproduced",
        baseline_display_name=str(config["baseline"]["display_name"]),
        baseline_runtime_config=runtime_config,
        allow_test_labels_during_development=bool(config["integrity"]["allow_test_labels_during_development"]),
        allow_test_score_command=bool(config["integrity"]["allow_test_score_command"]),
    )


def load_challenge_contract(path: str | Path = "configs/challenge/kuairand_pure.yaml") -> ChallengeContract:
    root = repository_root()
    load_dotenv(root / ".env", override=False)
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = root / config_path
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config.get("benchmark") == "kuairand_1k":
        return _load_bonus_contract(root, config)
    dataset_template = config["dataset"]["directory"]
    if dataset_template != "${KUAIRAND_DATA_DIR}":
        raise ValueError("challenge dataset path must come from KUAIRAND_DATA_DIR")
    dataset_value = os.getenv("KUAIRAND_DATA_DIR")
    if not dataset_value:
        raise ValueError("KUAIRAND_DATA_DIR is required")
    dataset_dir = Path(dataset_value)
    if not dataset_dir.is_absolute():
        dataset_dir = root / dataset_dir
    official = {name: root / value for name, value in config["official_files"].items()}
    missing_files = [str(item) for item in official.values() if not item.is_file()]
    if missing_files:
        raise FileNotFoundError(f"missing official files: {missing_files}")
    required_data = {
        "log_standard_4_08_to_4_21_pure.csv", "log_standard_4_22_to_5_08_pure.csv",
        "video_features_basic_pure.csv", "user_features_pure.csv",
    }
    missing_data = [name for name in sorted(required_data) if not (dataset_dir / name).is_file()]
    if missing_data:
        raise FileNotFoundError(f"missing KuaiRand files: {missing_data}")
    data_constants = _literal_assignments(official["data_loader"], {"LABEL", "SPLITS", "FIELDS"})
    submit_constants = _literal_assignments(official["submission_checker"], {"HEADER"})
    scores = json.loads(official["baseline_scores"].read_text(encoding="utf-8"))
    fm = scores["scores"]["fm_official"]
    return ChallengeContract(
        benchmark=config["benchmark"], dataset_dir=dataset_dir.resolve(), label=data_constants["LABEL"],
        splits={name: tuple(values) for name, values in data_constants["SPLITS"].items()},
        fields=list(data_constants["FIELDS"]), metrics=list(scores["metrics"]), primary_rule=scores["primary"],
        baseline_valid={key: float(value) for key, value in fm["valid"].items()},
        baseline_test={key: float(value) for key, value in fm["test"].items()},
        baseline_config=fm["config"], baseline_seed_std=float(fm["std_over_5_seeds"]["test_primary"]),
        convergence_epsilon=float(scores["convergence_rule"]["epsilon"]),
        convergence_patience=int(scores["convergence_rule"]["N"]), submission_header=submit_constants["HEADER"],
        sanity_shuffle_tolerance=float(config["integrity"]["sanity_shuffle_tolerance"]),
        official_files=official, official_hashes={name: sha256_file(file) for name, file in official.items()},
        allow_test_labels_during_development=bool(config["integrity"]["allow_test_labels_during_development"]),
        allow_test_score_command=bool(config["integrity"]["allow_test_score_command"]),
    )
