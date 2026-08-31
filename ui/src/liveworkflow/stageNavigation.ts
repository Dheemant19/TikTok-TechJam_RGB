import { GROUP_LABELS, NODES, RUN_ORDER } from "../data/nodeRegistry";

export type DetailSectionId = "summary" | "input" | "output" | "history";

export type FocusPhase = "closed" | "opening" | "open" | "transitioning" | "closing";

export interface OverlayRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface StageFocusState {
  selectedNodeId: string | null;
  previousNodeId: string | null;
  originRect: OverlayRect | null;
  phase: FocusPhase;
  activeSection: DetailSectionId;
  isAdvancing: boolean;
}

export const DETAIL_SECTIONS: Array<{ id: DetailSectionId; label: string }> = [
  { id: "summary", label: "Summary" },
  { id: "input", label: "Input" },
  { id: "output", label: "Output" },
  { id: "history", label: "History" },
];

export const TOTAL_STAGES = RUN_ORDER.length;

export function nodeForId(nodeId: string | null) {
  return nodeId ? NODES.find((node) => node.id === nodeId) ?? null : null;
}

export function nextStageId(nodeId: string, watchdogDecision?: string | null): string | null {
  if (nodeId === "recovery") return "evaluator";
  // A rejected decision loops back into another research cycle instead of
  // continuing on to Save Run Evidence (AGENTS.md #5); this is a visual/
  // navigation branch only and never changes backend routing.
  if (nodeId === "watchdog" && watchdogDecision === "reject") return "knowledge_mcp";
  const index = RUN_ORDER.indexOf(nodeId);
  if (index < 0 || index >= RUN_ORDER.length - 1) return null;
  return RUN_ORDER[index + 1];
}

export function stageNumberFor(nodeId: string): number | null {
  const index = RUN_ORDER.indexOf(nodeId);
  return index >= 0 ? index + 1 : null;
}

export function stageProgressLabel(nodeId: string): string {
  const stageNumber = stageNumberFor(nodeId);
  return stageNumber ? `Stage ${stageNumber} of ${TOTAL_STAGES}` : "Standby path";
}

export function laneMetaFor(nodeId: string): string {
  const node = nodeForId(nodeId);
  return node ? `${GROUP_LABELS[node.group]} / ${node.archLabel}` : "Stage details";
}

