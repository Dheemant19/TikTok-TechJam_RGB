// Hand-authored to exactly mirror src/rigor_rs/contract/models.py and
// src/rigor_rs/api/server.py. Regenerate/cross-check against a live server's
// OpenAPI document with `pnpm generate-api-types` (Plan_UI.md #1.4); the
// browser must never invent a second status vocabulary or metric schema.

export type ComponentStatus =
  | "waiting"
  | "ready"
  | "running"
  | "paused"
  | "succeeded"
  | "failed"
  | "rejected"
  | "skipped"
  | "blocked";

export type ComponentId =
  | "train_data"
  | "data_profiler"
  | "phase_guard"
  | "knowledge_mcp"
  | "scientist"
  | "coder"
  | "pruner"
  | "trainer"
  | "recovery"
  | "evaluator"
  | "watchdog"
  | "ledger"
  | "finalizer"
  | "submission";

export type AllowedAction = "pause" | "resume" | "cancel" | "package";

export interface FrontierState {
  validation_best: string | null;
  stable_fallback: string | null;
  accepted_parent: string | null;
  pending_candidate: string | null;
  rejected: string[];
  failed: string[];
  no_improvement_count: number;
  locked: boolean;
}

export interface SessionSnapshot {
  session_id: string;
  latest_sequence: number;
  status: ComponentStatus;
  component_states: Partial<Record<ComponentId, ComponentStatus>>;
  allowed_actions: AllowedAction[];
  current_run_id: string | null;
  metrics: Record<string, number>;
  frontier: FrontierState;
  finalized: boolean;
  cancelled: boolean;
}

export interface RunEvent {
  event_id: string;
  session_id: string;
  run_id: string;
  sequence: number;
  component_id: ComponentId;
  execution_id: string;
  stage: string;
  event_type: string;
  status: ComponentStatus;
  occurred_at: string;
  plain_summary: string;
  payload: Record<string, unknown>;
  artifact_ids: string[];
  previous_event_hash: string | null;
  event_hash: string;
}

export interface ArtifactRef {
  artifact_id: string;
  path: string;
  content_hash: string;
  media_type: string;
  taint: string | null;
  parent_ids: string[];
  row_count: number | null;
  schema_fingerprint: string | null;
  source_hashes: Record<string, string>;
  code_hash: string | null;
  created_at: string;
  content?: unknown;
}

export interface SessionListItem {
  session_id: string;
  status: ComponentStatus;
  created_at: string;
  latest_sequence: number;
  finalized: 0 | 1;
  cancelled: 0 | 1;
}

export interface ComponentExecution {
  component_id: ComponentId;
  execution_id: string;
  attempts: RunEvent[];
}

export interface ReplayResponse {
  mode: "replay";
  events: RunEvent[];
  final_snapshot: SessionSnapshot;
}

export interface StartSessionRequest {
  challenge_config_path: string;
  budget_config_path: string;
}

export interface StartSessionResponse {
  session_id: string;
  snapshot_url: string;
}

export interface ControlResponse {
  accepted: boolean;
  action: string;
}

export interface FinalizationManifest {
  session_id: string;
  validation_best: string;
  experiment_id: string;
  checkpoint_hash: string;
  transform_state_hash: string;
  predictions_hash: string;
  manifest_hash: string;
  schema_check: { command: string[]; stdout: string; exit_code: number };
  event_chain_valid: boolean;
  test_prediction_passes: number;
  created_at: string;
}

export interface ApiErrorBody {
  detail: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}
