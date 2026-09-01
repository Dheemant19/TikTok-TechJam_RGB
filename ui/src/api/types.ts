// Mirrors src/flowstate/contract/models.py. Keep field names identical to the
// backend's `model_dump(mode="json")` output -- the browser must not invent a
// second status vocabulary or metric schema (Plan_UI.md #1.4).

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type JsonRecord = Record<string, JsonValue>;

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

export type AllowedAction = "pause" | "resume" | "cancel" | "package";

export interface RunEventDTO {
  event_id: string;
  session_id: string;
  run_id: string;
  sequence: number;
  component_id: string;
  execution_id: string;
  stage: string;
  event_type: string;
  status: ComponentStatus;
  occurred_at: string;
  plain_summary: string;
  payload: JsonRecord;
  artifact_ids: string[];
  previous_event_hash: string | null;
  event_hash: string;
}

export interface FrontierStateDTO {
  validation_best: string | null;
  stable_fallback: string | null;
  accepted_parent: string | null;
  pending_candidate: string | null;
  rejected: string[];
  failed: string[];
  no_improvement_count: number;
  locked: boolean;
}

export interface SessionSnapshotDTO {
  session_id: string;
  latest_sequence: number;
  status: ComponentStatus;
  component_states: Record<string, ComponentStatus>;
  allowed_actions: AllowedAction[];
  current_run_id: string | null;
  metrics: Record<string, number>;
  frontier: FrontierStateDTO;
  finalized: boolean;
  cancelled: boolean;
  manual_interventions: number;
}

export interface SessionListItem {
  session_id: string;
  status: string;
  created_at: string;
  latest_sequence: number;
  finalized: number;
  cancelled: number;
}

export interface ChatTurnDTO {
  role: "user" | "assistant";
  content: string;
}

export interface SessionChatResponse {
  answer: string;
  model: string;
  reasoning_effort: string;
  usage: {
    input_tokens: number;
    output_tokens: number;
    model_id: string;
  };
}

export interface ArtifactResponse {
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
  content: JsonValue;
}

export const REDACTED_LABEL = "Hidden to protect data and credentials";
