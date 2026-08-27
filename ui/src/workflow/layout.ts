import type { Edge, Node } from "@xyflow/react";
import { GROUP_ORDER, NODE_REGISTRY, type WorkflowGroup } from "./nodeRegistry";
import type { ComponentId } from "@/api/types";

// Fixed left-to-right positions so the graph always reads as the true
// pipeline (Plan_UI.md #2.3). Users may temporarily drag nodes, but that is a
// session-local preference layered on top — see WorkflowCanvas.
const GROUP_X: Record<WorkflowGroup, number> = {
  data: 0,
  research: 340,
  code_safety: 680,
  train_score: 1020,
  decide_package: 1400,
};

const POSITIONS: Record<ComponentId, { x: number; y: number }> = {
  train_data: { x: GROUP_X.data, y: 0 },
  data_profiler: { x: GROUP_X.data, y: 140 },
  phase_guard: { x: GROUP_X.data, y: 280 },
  knowledge_mcp: { x: GROUP_X.research, y: 0 },
  scientist: { x: GROUP_X.research, y: 140 },
  coder: { x: GROUP_X.code_safety, y: 0 },
  pruner: { x: GROUP_X.code_safety, y: 140 },
  trainer: { x: GROUP_X.train_score, y: 0 },
  evaluator: { x: GROUP_X.train_score, y: 140 },
  recovery: { x: GROUP_X.train_score, y: 300 },
  watchdog: { x: GROUP_X.decide_package, y: 0 },
  ledger: { x: GROUP_X.decide_package, y: 140 },
  finalizer: { x: GROUP_X.decide_package, y: 280 },
  submission: { x: GROUP_X.decide_package, y: 420 },
};

export function buildInitialNodes(): Node[] {
  return Object.values(NODE_REGISTRY).map((definition) => ({
    id: definition.id,
    type: "workflow",
    position: POSITIONS[definition.id],
    data: { componentId: definition.id },
  }));
}

export const PRIMARY_EDGES: [ComponentId, ComponentId][] = [
  ["train_data", "data_profiler"],
  ["data_profiler", "phase_guard"],
  ["phase_guard", "knowledge_mcp"],
  ["knowledge_mcp", "scientist"],
  ["scientist", "coder"],
  ["coder", "pruner"],
  ["pruner", "trainer"],
  ["trainer", "evaluator"],
  ["evaluator", "watchdog"],
  ["watchdog", "ledger"],
  ["watchdog", "scientist"],
  ["ledger", "finalizer"],
  ["finalizer", "submission"],
];

// Recovery sits beside training and reconnects to the last stable parent —
// shown as dashed, secondary edges rather than the primary left-to-right flow.
export const RECOVERY_EDGES: [ComponentId, ComponentId][] = [
  ["trainer", "recovery"],
  ["recovery", "trainer"],
  ["recovery", "scientist"],
];

export function buildInitialEdges(): Edge[] {
  const primary: Edge[] = PRIMARY_EDGES.map(([source, target]) => ({
    id: `${source}->${target}`,
    source,
    target,
    type: "smoothstep",
  }));
  const recovery: Edge[] = RECOVERY_EDGES.map(([source, target]) => ({
    id: `${source}~>${target}`,
    source,
    target,
    type: "smoothstep",
    style: { strokeDasharray: "4 4", opacity: 0.55 },
  }));
  return [...primary, ...recovery];
}

export { GROUP_ORDER };
