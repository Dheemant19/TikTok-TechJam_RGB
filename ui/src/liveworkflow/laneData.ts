import type { CSSProperties } from "react";
import { GROUP_ORDER, NODES, NodeDef } from "../data/nodeRegistry";

export interface LaneColor {
  a: string;
  b: string;
  shadow: string;
  text: string;
}

// Indexed to match GROUP_ORDER: data, research, code, train, decide.
export const LANE_COLORS: LaneColor[] = [
  { a: "#22d3ee", b: "#06b6d4", shadow: "rgba(6,182,212,.32)", text: "#0e7490" },
  { a: "#a78bfa", b: "#8b5cf6", shadow: "rgba(139,92,246,.32)", text: "#6d28d9" },
  { a: "#fbbf24", b: "#f59e0b", shadow: "rgba(245,158,11,.32)", text: "#b45309" },
  { a: "#fb7185", b: "#f43f5e", shadow: "rgba(244,63,94,.32)", text: "#be123c" },
  { a: "#60a5fa", b: "#3b82f6", shadow: "rgba(59,130,246,.32)", text: "#1d4ed8" },
];
export const RECOVERY_COLOR = LANE_COLORS[3];

export function laneIndex(group: NodeDef["group"]): number {
  return GROUP_ORDER.indexOf(group);
}

export function laneColorFor(node: NodeDef): LaneColor {
  return node.isRecovery ? RECOVERY_COLOR : LANE_COLORS[laneIndex(node.group)];
}

export const LANE_X = [50, 340, 630, 920, 1210];
export const LANE_COUNTS = GROUP_ORDER.map((g) => NODES.filter((n) => n.group === g).length);
export const MAX_COUNT = Math.max(...LANE_COUNTS);
export const ROW_GAP = 178;
export const NODE_W = 224;
export const NODE_H = 128;

export interface Vec2 {
  x: number;
  y: number;
}

export function computeInitialPositions(): Record<string, Vec2> {
  const laneCursor: Record<number, number> = {};
  const pos: Record<string, Vec2> = {};
  NODES.forEach((n) => {
    const lane = laneIndex(n.group);
    const i = laneCursor[lane] || 0;
    laneCursor[lane] = i + 1;
    const startY = 40 + ((MAX_COUNT - LANE_COUNTS[lane]) * ROW_GAP) / 2;
    pos[n.id] = { x: LANE_X[lane], y: startY + i * ROW_GAP };
  });
  return pos;
}

export interface Fact {
  label: string;
  value: string;
}
export interface FieldRow {
  label: string;
  value: string;
  mono?: boolean;
}
export interface HistoryRow {
  attempt: number;
  status: string;
  time: string;
  note: string;
  dotColor: string;
}
export interface NodeDetail {
  summary: string;
  facts: Fact[];
  input: FieldRow[];
  output: FieldRow[];
  history: HistoryRow[];
}

export const NODE_DETAILS: Record<string, NodeDetail> = {
  train_data: {
    summary:
      "Provides the frozen train/validation split used across the whole run. Read-only source of interaction rows for the Data Profiler.",
    facts: [
      { label: "Rows", value: "2.4M interactions" },
      { label: "Users", value: "182,400" },
      { label: "Split", value: "Train / Val / Test" },
      { label: "Format", value: "Parquet, KuaiRand schema" },
    ],
    input: [
      { label: "Source path", value: "Hidden to protect data and credentials" },
      { label: "Config", value: "challenge_config.yaml" },
    ],
    output: [
      { label: "Split manifest", value: "train: 1.9M · val: 250K · test: 250K" },
      { label: "Schema hash", value: "8f2c…a91d", mono: true },
    ],
    history: [{ attempt: 1, status: "Succeeded", time: "09:12:04", note: "Loaded and validated schema", dotColor: "#22c55e" }],
  },
  data_profiler: {
    summary:
      "Fits train-only transforms (vocabularies, bucket edges, scalers) and applies the frozen artifact to validation and test features without refitting.",
    facts: [
      { label: "long_view prevalence", value: "31.2%" },
      { label: "Unseen-ID rate", value: "0.8%" },
      { label: "Missing fields", value: "3 flagged" },
      { label: "Transform", value: "Frozen, train-only" },
    ],
    input: [{ label: "Raw interactions", value: "Hidden to protect data and credentials" }],
    output: [
      { label: "profile.json", value: "Aggregate diagnostics, bounded bins" },
      { label: "transform_receipt.json", value: "source hash → fitted hash → artifact hash", mono: true },
    ],
    history: [{ attempt: 1, status: "Succeeded", time: "09:12:41", note: "Profile and receipt generated", dotColor: "#22c55e" }],
  },
  phase_guard: {
    summary:
      "Checks the prepared data against safety rules before it reaches the research and training stages. Blocks the run if a check fails.",
    facts: [
      { label: "Checks run", value: "12" },
      { label: "Result", value: "All passed" },
      { label: "Leakage check", value: "Clear" },
      { label: "Label check", value: "Clear" },
    ],
    input: [{ label: "Transform receipt", value: "From Data Profiler" }],
    output: [{ label: "Decision", value: "Approved to continue" }],
    history: [{ attempt: 1, status: "Succeeded", time: "09:13:02", note: "No safety violations found", dotColor: "#22c55e" }],
  },
  knowledge_mcp: {
    summary: "Searches curated and auto-ingested research sources for evidence relevant to the current experiment frontier.",
    facts: [
      { label: "Sources found", value: "6" },
      { label: "Curated", value: "4" },
      { label: "Auto-ingested", value: "2" },
      { label: "License checked", value: "Yes" },
    ],
    input: [{ label: "Query", value: "sequence modeling for long-view prediction under censoring" }],
    output: [{ label: "Evidence cards", value: "6 with citations and retrieval time" }],
    history: [{ attempt: 1, status: "Succeeded", time: "09:13:20", note: "Evidence retrieved and cached", dotColor: "#22c55e" }],
  },
  scientist: {
    summary: "Chooses the next experiment to try, informed by research evidence, the current best model, and remaining budget.",
    facts: [
      { label: "Candidate", value: "Attention pooling over session" },
      { label: "Budget used", value: "18%" },
      { label: "Parent", value: "stable fallback" },
      { label: "Rationale", value: "Evidence-backed" },
    ],
    input: [
      { label: "Evidence cards", value: "From Research Agent" },
      { label: "Current best", value: "primary score 0.601" },
    ],
    output: [{ label: "Experiment plan", value: "Attention pooling + duration-aware loss" }],
    history: [{ attempt: 1, status: "Succeeded", time: "09:13:55", note: "Experiment selected", dotColor: "#22c55e" }],
  },
  coder: {
    summary: "Writes the code change implementing the selected experiment, then hands it to fast safety tests before training.",
    facts: [
      { label: "Files changed", value: "3" },
      { label: "Lines", value: "+142 / −18" },
      { label: "Diff type", value: "Unified" },
      { label: "Secrets", value: "Hidden to protect data and credentials" },
    ],
    input: [{ label: "Experiment plan", value: "From Choose the Next Experiment" }],
    output: [{ label: "Patch", value: "model/pooling.py, train/loss.py, config.yaml" }],
    history: [{ attempt: 1, status: "Succeeded", time: "09:14:30", note: "Patch generated", dotColor: "#22c55e" }],
  },
  pruner: {
    summary: "Runs a fast, cheap test suite to catch broken code before committing to a full training run.",
    facts: [
      { label: "Tests run", value: "34" },
      { label: "Passed", value: "34" },
      { label: "Duration", value: "42s" },
      { label: "Smoke train", value: "2 steps, no NaN" },
    ],
    input: [{ label: "Patch", value: "From Write the Code Change" }],
    output: [{ label: "Result", value: "All fast tests passed" }],
    history: [{ attempt: 1, status: "Succeeded", time: "09:15:12", note: "Cleared for full training", dotColor: "#22c55e" }],
  },
  trainer: {
    summary: "Trains the model on the frozen train split. On failure, hands off to the recovery agent and resumes from the last checkpoint.",
    facts: [
      { label: "GPU-hours", value: "1.4" },
      { label: "Steps", value: "12,000" },
      { label: "Peak memory", value: "18.2 GB" },
      { label: "Checkpoints", value: "3" },
    ],
    input: [{ label: "Patch + config", value: "From Write the Code Change" }],
    output: [{ label: "Model checkpoint", value: "Hidden to protect data and credentials" }],
    history: [{ attempt: 1, status: "Succeeded", time: "09:22:48", note: "Training completed, converged", dotColor: "#22c55e" }],
  },
  recovery: {
    summary: "Standby agent. Activates only when training fails or diverges, restoring the last stable checkpoint and reconnecting to its parent stage.",
    facts: [
      { label: "Status", value: "On standby" },
      { label: "Last activation", value: "None this run" },
      { label: "Reconnects to", value: "Train the Model" },
      { label: "Preserves", value: "Full run history" },
    ],
    input: [{ label: "Trigger", value: "Training failure or divergence signal" }],
    output: [{ label: "Restored state", value: "Last stable checkpoint (if activated)" }],
    history: [{ attempt: 0, status: "Standby", time: "—", note: "Not activated this run", dotColor: "#94a3b8" }],
  },
  evaluator: {
    summary: "Scores the trained model on the held-out validation split using the authoritative evaluation code. This is the only source of truth for metrics.",
    facts: [
      { label: "GAUC", value: "0.641" },
      { label: "nDCG@5", value: "0.318" },
      { label: "Primary score", value: "0.614" },
      { label: "vs. baseline", value: "+2.2%" },
    ],
    input: [
      { label: "Model checkpoint", value: "From Train the Model" },
      { label: "Eval split", value: "Held-out validation" },
    ],
    output: [{ label: "Metrics", value: "GAUC 0.641 · nDCG@5 0.318 · primary 0.614" }],
    history: [{ attempt: 1, status: "Succeeded", time: "09:24:10", note: "Evaluation complete", dotColor: "#22c55e" }],
  },
  watchdog: {
    summary: "Decides whether the run continues to another experiment or stops, based on convergence and remaining budget. This decision is authoritative.",
    facts: [
      { label: "Decision", value: "Continue" },
      { label: "Budget remaining", value: "62%" },
      { label: "Convergence", value: "Not yet reached" },
      { label: "Consecutive rejects", value: "0" },
    ],
    input: [
      { label: "Metrics", value: "From Score on Validation" },
      { label: "Budget state", value: "From budget_config.yaml" },
    ],
    output: [{ label: "Decision", value: "Continue — new best accepted" }],
    history: [{ attempt: 1, status: "Succeeded", time: "09:24:22", note: "Decision recorded", dotColor: "#22c55e" }],
  },
  ledger: {
    summary: "Records every step of this run as an ordered, append-only event log used for live viewing, replay, and audit.",
    facts: [
      { label: "Events this run", value: "13" },
      { label: "Storage", value: "Local SQLite" },
      { label: "Replay-ready", value: "Yes" },
      { label: "Tamper checks", value: "Hash-chained" },
    ],
    input: [{ label: "Run events", value: "From all pipeline stages" }],
    output: [{ label: "Event log", value: "13 events, sequence 1–13" }],
    history: [{ attempt: 1, status: "Succeeded", time: "09:24:30", note: "Run evidence saved", dotColor: "#22c55e" }],
  },
  finalizer: {
    summary: "Builds the final submission package once the watchdog signals convergence or a budget stop, and only after explicit confirmation.",
    facts: [
      { label: "Trigger", value: "Convergence or budget stop" },
      { label: "Confirmation", value: "Session ID required" },
      { label: "Manifest", value: "Hash-verified" },
      { label: "Replay check", value: "Clean" },
    ],
    input: [{ label: "Best checkpoint", value: "Validation-best" }],
    output: [{ label: "Package", value: "Prediction schema checked, manifest hashed" }],
    history: [{ attempt: 0, status: "Waiting", time: "—", note: "Awaiting convergence or stop", dotColor: "#94a3b8" }],
  },
  submission: {
    summary: "The final, one-way artifact produced by this run. Once built, this boundary cannot be reopened by the UI.",
    facts: [
      { label: "Status", value: "Not yet built" },
      { label: "Schema check", value: "Pending" },
      { label: "Boundary", value: "One-way, explicit" },
      { label: "Source", value: "Build Final Package" },
    ],
    input: [{ label: "Final package", value: "From Build Final Package" }],
    output: [{ label: "Predictions", value: "Pending finalization" }],
    history: [{ attempt: 0, status: "Waiting", time: "—", note: "Pipeline not yet finalized", dotColor: "#94a3b8" }],
  },
};

export type BadgeShape = CSSProperties;

export function shapeStyle(group: NodeDef["group"], isRecovery?: boolean): BadgeShape {
  if (isRecovery) return { borderRadius: "10px", border: "2px dashed rgba(148,163,184,.7)" };
  const shapes: BadgeShape[] = [
    { borderRadius: "10px" },
    { borderRadius: "50%" },
    { borderRadius: "7px", transform: "rotate(45deg)" },
    { clipPath: "polygon(50% 0%, 100% 38%, 82% 100%, 18% 100%, 0% 38%)" },
    { clipPath: "polygon(25% 4%, 75% 4%, 100% 50%, 75% 96%, 25% 96%, 0% 50%)" },
  ];
  return shapes[laneIndex(group)];
}
