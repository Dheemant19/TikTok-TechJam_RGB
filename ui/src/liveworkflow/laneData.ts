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
  { a: "var(--group-data-a)", b: "var(--group-data-b)", shadow: "var(--group-data-shadow)", text: "var(--group-data-text)" },
  { a: "var(--group-research-a)", b: "var(--group-research-b)", shadow: "var(--group-research-shadow)", text: "var(--group-research-text)" },
  { a: "var(--group-code-a)", b: "var(--group-code-b)", shadow: "var(--group-code-shadow)", text: "var(--group-code-text)" },
  { a: "var(--group-train-a)", b: "var(--group-train-b)", shadow: "var(--group-train-shadow)", text: "var(--group-train-text)" },
  { a: "var(--group-decide-a)", b: "var(--group-decide-b)", shadow: "var(--group-decide-shadow)", text: "var(--group-decide-text)" },
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

export interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
  centerX: number;
  centerY: number;
}

export function contentBounds(positions: Record<string, Vec2>): Bounds {
  const xs = Object.values(positions).map((p) => p.x);
  const ys = Object.values(positions).map((p) => p.y);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const maxX = Math.max(...xs) + NODE_W;
  const maxY = Math.max(...ys) + NODE_H;
  return { minX, minY, maxX, maxY, centerX: (minX + maxX) / 2, centerY: (minY + maxY) / 2 };
}

/**
 * The y a rejected-decision loop arch (e.g. watchdog -> knowledge_mcp) must
 * clear to stay above every card it visually crosses. Only the lanes
 * strictly between the two endpoints' own lanes are obstacles -- the
 * endpoint lanes themselves are excluded because the arch starts/ends AT
 * those nodes rather than passing over them, and an unrelated lane (e.g.
 * Data, never between Decide and Research) must never inflate the
 * clearance the way using every node's global minimum y previously did.
 * `LaneScaffold`/`FocusLaneScaffolds` render each lane's box 58px above its
 * own topmost node; clearing that chrome by another 40px reads as a real
 * overpass rather than a graze. Shared by `EdgesLayer` (the actual path)
 * and `FocusArchitecturePane` (which must reserve enough vertical room in
 * its own fit-to-view bounds so the arch is never clipped).
 */
export function loopClearanceY(positions: Record<string, Vec2>, from: string, to: string): number {
  const fromNode = NODES.find((node) => node.id === from);
  const toNode = NODES.find((node) => node.id === to);
  if (!fromNode || !toNode) return Math.min(positions[from]?.y ?? 0, positions[to]?.y ?? 0);
  const fromLane = laneIndex(fromNode.group);
  const toLane = laneIndex(toNode.group);
  const crossedGroups = GROUP_ORDER.slice(Math.min(fromLane, toLane) + 1, Math.max(fromLane, toLane));
  const crossedNodes = NODES.filter((node) => crossedGroups.includes(node.group));
  const crossedTopY = crossedNodes.length > 0
    ? Math.min(...crossedNodes.map((node) => positions[node.id].y))
    : Math.min(positions[from].y, positions[to].y);
  return crossedTopY - 58 - 40;
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

// Static per-node content is limited to architectural description: what the
// stage does and what it is wired to. Every number, metric, hash, timestamp
// and count must come from the live ledger via nodeDetail.ts. Placeholder
// telemetry here previously rendered as real readings whenever a stage had
// not produced its own data yet (e.g. an unrun evaluator showed a GAUC and a
// "vs. baseline" delta), which is exactly the fabrication AGENTS.md forbids.
export const NODE_DETAILS: Record<string, NodeDetail> = {
  train_data: {
    summary:
      "Provides the frozen train/validation split used across the whole run. Read-only source of interaction rows for the Data Profiler.",
    facts: [],
    input: [
      { label: "Source path", value: "Hidden to protect data and credentials" },
      { label: "Config", value: "configs/challenge/kuairand_pure.yaml", mono: true },
    ],
    output: [],
    history: [],
  },
  data_profiler: {
    summary:
      "Fits train-only transforms (vocabularies, bucket edges, scalers) and applies the frozen artifact to validation and test features without refitting.",
    facts: [],
    input: [{ label: "Raw interactions", value: "Hidden to protect data and credentials" }],
    output: [],
    history: [],
  },
  phase_guard: {
    summary:
      "Checks the prepared data against safety rules before it reaches the research and training stages. Blocks the run if a check fails.",
    facts: [],
    input: [{ label: "Transform receipt", value: "From Data Profiler" }],
    output: [],
    history: [],
  },
  initial_baseline: {
    summary:
      "Reproduces the official Factorization Machine baseline on the frozen validation split. This score is the fixed target every experiment is compared against for the rest of the run.",
    facts: [],
    input: [{ label: "Transform receipt", value: "From Inspect & Prepare Data" }],
    output: [],
    history: [],
  },
  knowledge_mcp: {
    summary: "Searches curated and auto-ingested research sources for evidence relevant to the current experiment frontier.",
    facts: [],
    input: [{ label: "Query", value: "Derived from the current experiment frontier" }],
    output: [],
    history: [],
  },
  scientist: {
    summary: "Chooses the next experiment to try, informed by research evidence, the current best model, and remaining budget.",
    facts: [],
    input: [
      { label: "Evidence cards", value: "From Find Research Evidence" },
      { label: "Current best", value: "From the frontier recorded in the ledger" },
    ],
    output: [],
    history: [],
  },
  coder: {
    summary: "Writes the code change implementing the selected experiment, then hands it to fast safety tests before training.",
    facts: [],
    input: [{ label: "Experiment plan", value: "From Choose the Next Experiment" }],
    output: [],
    history: [],
  },
  pruner: {
    summary: "Runs a fast, cheap test suite to catch broken code before committing to a full training run.",
    facts: [],
    input: [{ label: "Patch", value: "From Write the Code Change" }],
    output: [],
    history: [],
  },
  proxy_gate: {
    summary:
      "Runs a cheap, small-scale training pass to filter out patches with no measurable effect before committing GPU time to a full run. Proxy scores are filter-only and are never compared to the official GAUC, nDCG@5, or primary score.",
    facts: [],
    input: [{ label: "Patch", value: "From Run Fast Safety Tests" }],
    output: [],
    history: [],
  },
  trainer: {
    summary: "Trains the model on the frozen train split. On failure, hands off to the recovery agent and resumes from the last checkpoint.",
    facts: [],
    input: [{ label: "Patch + config", value: "From Write the Code Change" }],
    output: [],
    history: [],
  },
  recovery: {
    summary: "Standby agent. Activates only when training fails or diverges, restoring the last stable checkpoint and reconnecting to its parent stage.",
    facts: [],
    input: [{ label: "Trigger", value: "Training failure or divergence signal" }],
    output: [],
    history: [],
  },
  evaluator: {
    summary: "Scores the trained model on the held-out validation split using the authoritative evaluation code. This is the only source of truth for metrics.",
    facts: [],
    input: [
      { label: "Model checkpoint", value: "From Train the Model" },
      { label: "Eval split", value: "Held-out validation" },
    ],
    output: [],
    history: [],
  },
  watchdog: {
    summary: "Decides whether the run continues to another experiment or stops, based on convergence and remaining budget. This decision is authoritative.",
    facts: [],
    input: [
      { label: "Metrics", value: "From Score on Validation" },
      { label: "Budget state", value: "configs/budgets/*.yaml", mono: true },
    ],
    output: [],
    history: [],
  },
  ledger: {
    summary: "Records every step of this run as an ordered, append-only event log used for live viewing, replay, and audit.",
    facts: [],
    input: [{ label: "Run events", value: "From all pipeline stages" }],
    output: [],
    history: [],
  },
  finalizer: {
    summary: "Builds the final submission package once the watchdog signals convergence or a budget stop, and only after explicit confirmation.",
    facts: [],
    input: [{ label: "Best checkpoint", value: "Validation-best" }],
    output: [],
    history: [],
  },
  submission: {
    summary: "The final, one-way artifact produced by this run. Once built, this boundary cannot be reopened by the UI.",
    facts: [],
    input: [{ label: "Final package", value: "From Build Final Package" }],
    output: [],
    history: [],
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
