from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SplitTaint(StrEnum):
    TRAIN_FEATURES = "TRAIN_FEATURES"
    TRAIN_LABELS = "TRAIN_LABELS"
    VALIDATION_FEATURES = "VALIDATION_FEATURES"
    VALIDATION_LABELS = "VALIDATION_LABELS"
    VALIDATION_FEEDBACK = "VALIDATION_FEEDBACK"
    TEST_FEATURES_ONLY = "TEST_FEATURES_ONLY"
    TEST_LABELS_LOCKED = "TEST_LABELS_LOCKED"


class ComponentStatus(StrEnum):
    WAITING = "waiting"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


COMPONENT_IDS = {
    "train_data", "data_profiler", "phase_guard", "knowledge_mcp", "scientist",
    "coder", "pruner", "trainer", "recovery", "evaluator", "watchdog",
    "ledger", "finalizer", "submission",
}


class ArtifactRef(StrictModel):
    artifact_id: str
    path: Path
    content_hash: str
    media_type: str
    taint: SplitTaint | None = None
    parent_ids: list[str] = Field(default_factory=list)
    row_count: int | None = None
    schema_fingerprint: str | None = None
    source_hashes: dict[str, str] = Field(default_factory=dict)
    code_hash: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class DataArtifact(StrictModel):
    artifact_id: str
    path: Path
    taints: set[SplitTaint]
    parent_ids: list[str] = Field(default_factory=list)
    row_count: int
    schema_fingerprint: str
    source_hash: str
    code_hash: str
    creation_receipt_id: str


class ProfileConfig(StrictModel):
    maximum_categories: int = Field(default=100, ge=1)
    histogram_bins: int = Field(default=20, ge=5, le=100)
    sample_rows: int | None = Field(default=None, ge=1)


class ProfileReceipt(StrictModel):
    receipt_id: str
    profile: ArtifactRef
    visualization: ArtifactRef
    input_hash: str
    cache_hit: bool
    warnings: list[str] = Field(default_factory=list)


class TransformSpec(StrictModel):
    name: str = "official_fm"
    fields: list[str] = Field(default_factory=lambda: ["user_id", "video_id", "author_id", "tab", "dur_bucket"])
    duration_quantiles: int = Field(default=10, ge=2)
    protected_columns: list[str] = Field(default_factory=lambda: ["row_id", "user_id", "video_id", "date", "long_view"])
    seed: int = 0


class TransformReceipt(StrictModel):
    receipt_id: str
    state: ArtifactRef
    spec: ArtifactRef
    receipt: ArtifactRef
    materializations: dict[str, ArtifactRef]
    cache_hit: bool


class RunEvent(StrictModel):
    event_id: str
    session_id: str
    run_id: str
    sequence: int
    component_id: str
    execution_id: str
    stage: str
    event_type: str
    status: ComponentStatus
    occurred_at: str
    plain_summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    artifact_ids: list[str] = Field(default_factory=list)
    previous_event_hash: str | None = None
    event_hash: str

    @model_validator(mode="after")
    def valid_component(self) -> "RunEvent":
        if self.component_id not in COMPONENT_IDS:
            raise ValueError(f"unknown component_id: {self.component_id}")
        return self


class MetricReceipt(StrictModel):
    receipt_id: str
    run_id: str
    prediction_artifact_id: str
    evaluator_hash: str
    config_hash: str
    gauc: float
    ndcg_at_5: float
    primary: float
    users: int
    rows: int
    comparable: bool = True
    scope: Literal["proxy", "validation", "test"] = "validation"
    occurred_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    receipt_hash: str


class OutcomeBranches(StrictModel):
    success: str
    ambiguous: str
    regression: str


class ExperimentBudget(StrictModel):
    wall_seconds: int = Field(gt=0)
    gpu_hours: float = Field(ge=0)
    bedrock_input_tokens: int = Field(ge=0)
    bedrock_output_tokens: int = Field(ge=0)


class ExperimentContract(StrictModel):
    experiment_id: str
    parent_run_id: str
    hypothesis: str = Field(min_length=20)
    observed_evidence_ids: list[str] = Field(
        description=(
            "Each entry must be copied verbatim from one supplied evidence item's "
            "paper_id field (e.g. 'arxiv:1205.2618'), never a content_hash, title, "
            "or any other value."
        ),
    )
    primary_change: str
    allowed_files: list[str]
    prohibited_files: list[str]
    predicted_gauc_direction: Literal["up", "flat", "down"]
    predicted_ndcg_at_5_direction: Literal["up", "flat", "down"]
    falsifiers: list[str]
    outcome_branches: OutcomeBranches
    comparator_run_id: str
    minimum_primary_improvement: float
    guardrails: list[str]
    budget: ExperimentBudget
    fallback_run_id: str
    recovery_attempt_limit: int = Field(ge=0, le=5)

    @model_validator(mode="after")
    def bounded_change(self) -> "ExperimentContract":
        if not self.allowed_files:
            raise ValueError("at least one allowed file is required")
        return self


class DependencyChange(StrictModel):
    package: str
    version: str
    license: str
    necessity: str


class PatchProposal(StrictModel):
    unified_diff: str = Field(
        min_length=1,
        description=(
            "Raw standard git unified diff containing diff --git, --- a/, +++ b/, "
            "and complete @@ -OLD_START,OLD_COUNT +NEW_START,NEW_COUNT @@ hunk headers "
            "with real line numbers; no bare @@, Markdown fences, or custom patch markers."
        ),
    )
    dependency_changes: list[DependencyChange] = Field(default_factory=list)
    tests: list[str] = Field(
        default_factory=list,
        description=(
            "Relative pytest targets only, such as tests/workflow/test_decisions.py "
            "or a ::test_name node ID; never a python/pytest shell command."
        ),
    )
    explanation: str


class RecoveryReceipt(StrictModel):
    recovery_id: str
    run_id: str
    category: str
    original_error: str
    diagnosis: str
    action: str
    attempt: int
    result: str


class FrontierState(StrictModel):
    validation_best: str | None = None
    stable_fallback: str | None = None
    accepted_parent: str | None = None
    pending_candidate: str | None = None
    rejected: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    no_improvement_count: int = 0
    locked: bool = False


class SessionSnapshot(StrictModel):
    session_id: str
    latest_sequence: int = 0
    status: ComponentStatus = ComponentStatus.WAITING
    component_states: dict[str, ComponentStatus] = Field(default_factory=dict)
    allowed_actions: list[Literal["pause", "resume", "cancel", "package"]] = Field(default_factory=list)
    current_run_id: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    frontier: FrontierState = Field(default_factory=FrontierState)
    finalized: bool = False
    cancelled: bool = False
    manual_interventions: int = 0


class ResourceTotals(StrictModel):
    wall_seconds: float = 0
    gpu_hours: float | None = None
    bedrock_input_tokens: int = 0
    bedrock_output_tokens: int = 0
    peak_gpu_memory_mb: float | None = None
    peak_rss_mb: float = 0
    retries: int = 0
    manual_interventions: int = 0
