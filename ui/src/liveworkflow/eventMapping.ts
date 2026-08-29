import type { RunEventDTO } from "../api/types";
import { NODES, type NodeStatus } from "../data/nodeRegistry";

export interface NodeRuntimeState {
  status: NodeStatus;
  startedAt: string | null;
  events: RunEventDTO[];
}

function idleStates(): Record<string, NodeRuntimeState> {
  return Object.fromEntries(NODES.map((node) => [node.id, { status: "waiting" as NodeStatus, startedAt: null, events: [] }]));
}

/**
 * The backend's four-tier execution funnel (AGENTS.md, Plan_Workflow.md #10)
 * reports every tier under the single `trainer` component_id, distinguished
 * by `event_type`. The canvas keeps Tier 1 ("Run Fast Safety Tests") as its
 * own `pruner` node, so Tier 1 events are re-routed there; everything else
 * from `trainer` (baseline training, Tier 2-4, resource usage) stays on the
 * `trainer` node.
 */
function uiNodeIdForEvent(event: RunEventDTO): string {
  if (event.component_id === "trainer" && event.stage === "execute" && event.event_type === "tier1") return "pruner";
  return event.component_id;
}

// Nodes that execute strictly in this order within one experiment iteration.
// `ledger`, `finalizer`, `submission`, and `recovery` are cross-cutting or
// standby and are deliberately excluded: they must never backfill the core
// loop's status.
const CORE_LOOP_ORDER = ["train_data", "data_profiler", "knowledge_mcp", "scientist", "coder", "pruner", "trainer", "evaluator", "watchdog"];

export function deriveNodeStates(events: RunEventDTO[]): Record<string, NodeRuntimeState> {
  const states = idleStates();
  let profilerCompleted = false;
  let integrityHaltSeen = false;

  for (const event of events) {
    const targetId = uiNodeIdForEvent(event);
    const state = states[targetId];
    if (!state) continue;
    state.events.push(event);
    state.status = event.status;
    state.startedAt = event.status === "running" ? event.occurred_at : state.startedAt;

    if (event.component_id === "data_profiler" && event.event_type === "completed") profilerCompleted = true;
    if (event.component_id === "phase_guard") integrityHaltSeen = true;
    // `trainer` also represents the pre-research baseline reproduction
    // (orchestration/graph.py `baseline()`), which sits before `scientist`
    // in the CORE_LOOP_ORDER backfill below. Research only starts once
    // baseline has synchronously returned, so a `knowledge_mcp` event is an
    // explicit signal that a still-"running" baseline has succeeded.
    if (event.component_id === "knowledge_mcp" && states.trainer.status === "running") states.trainer.status = "succeeded";

    // Control-plane events (pause/resume/cancel) target `watchdog` but do not
    // mean the pipeline actually advanced past every earlier stage, so they
    // must never trigger the structural backfill below.
    if (event.event_type.startsWith("control_")) continue;

    const index = CORE_LOOP_ORDER.indexOf(targetId);
    if (index <= 0) continue;
    // LangGraph nodes run strictly in sequence within one experiment
    // iteration (orchestration/graph.py): once a later core-loop stage has
    // reported activity, any earlier stage still marked "running" has
    // synchronously returned, i.e. it succeeded, even though the backend
    // does not emit an explicit terminal event for every stage (for example
    // the baseline-training half of `trainer`).
    for (let i = 0; i < index; i++) {
      const priorState = states[CORE_LOOP_ORDER[i]];
      if (priorState.status === "running") priorState.status = "succeeded";
    }
  }

  // `phase_guard` (Plan_Workflow.md #5, "Pipeline Sanity Checks") only emits
  // an event on failure (orchestration/graph.py `baseline()`), so a silent
  // pass is inferred from data profiling having completed with no halt seen.
  if (profilerCompleted) states.phase_guard.status = integrityHaltSeen ? "blocked" : "succeeded";

  return states;
}

export function nodeStatusMap(states: Record<string, NodeRuntimeState>): Record<string, NodeStatus> {
  return Object.fromEntries(Object.entries(states).map(([id, state]) => [id, state.status]));
}

export function eventsForNode(states: Record<string, NodeRuntimeState>, nodeId: string): RunEventDTO[] {
  return states[nodeId]?.events ?? [];
}
