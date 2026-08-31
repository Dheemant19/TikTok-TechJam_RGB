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
 * reports every tier under the single `trainer` component_id, and the
 * pre-research baseline reproduction also shares `trainer` under
 * `stage: "baseline"` (orchestration/graph.py `baseline()`). The canvas
 * keeps each of these as its own presentation node -- Tier 1 stays `pruner`,
 * baseline reproduction becomes `initial_baseline`, and the mid-funnel proxy
 * tiers (2-3) become `proxy_gate` -- so `trainer` itself only ever
 * represents Tier 4 (full-scale training) and resource-usage receipts.
 *
 * `phase_guard` similarly reports two structurally different things under
 * one component_id: a real data/baseline safety gate at `stage: "baseline"`
 * (the only case that may ever block `phase_guard` / Check Data Safety), and
 * a proxy-only rejection (e.g. `inert_patch`) at `stage: "execute"`, which
 * must never touch the data-safety card and is routed to `proxy_gate`
 * instead (AGENTS.md non-negotiable: a proxy failure must never mark Check
 * Data Safety as Blocked).
 */
export function uiNodeIdForEvent(event: RunEventDTO): string {
  if (event.component_id === "trainer") {
    if (event.stage === "baseline") return "initial_baseline";
    if (event.stage === "execute" && event.event_type === "tier1") return "pruner";
    if (event.stage === "execute" && (event.event_type === "tier2" || event.event_type === "tier3")) return "proxy_gate";
    return "trainer"; // tier4, the generic execute-funnel failure, and resource-usage receipts.
  }
  if (event.component_id === "phase_guard" && event.stage === "execute") return "proxy_gate";
  return event.component_id;
}

// Nodes that execute strictly in this order within one experiment iteration.
// `ledger`, `finalizer`, `submission`, and `recovery` are cross-cutting or
// standby and are deliberately excluded: they must never backfill the core
// loop's status. `initial_baseline` and `proxy_gate` sit at their real
// temporal position in the funnel so a later event (e.g. the first
// `knowledge_mcp` event, or a `trainer` Tier 4 event) correctly backfills a
// still-"running" earlier stage to "succeeded" without a special case.
const CORE_LOOP_ORDER = [
  "train_data", "data_profiler", "initial_baseline", "knowledge_mcp", "scientist",
  "coder", "pruner", "proxy_gate", "trainer", "evaluator", "watchdog",
];

// Cards that represent session-level data preparation, safety, and baseline
// state and must persist across experiment iterations (AGENTS.md #6).
const PERSISTENT_DATA_NODES: Record<string, true> = { train_data: true, data_profiler: true, phase_guard: true, initial_baseline: true };

function applyEvent(
  states: Record<string, NodeRuntimeState>,
  event: RunEventDTO,
  flags: { integrityHaltSeen: boolean },
): void {
  const targetId = uiNodeIdForEvent(event);
  const state = states[targetId];
  if (!state) return;
  state.events.push(event);
  state.status = event.status;
  state.startedAt = event.status === "running" ? event.occurred_at : state.startedAt;

  // Only a real data/baseline safety-gate event (stage "baseline") may ever
  // block Check Data Safety -- a proxy-stage phase_guard event is routed to
  // `proxy_gate` above and must never set this flag.
  if (
    event.component_id === "phase_guard"
    && event.stage === "baseline"
    && (event.status === "blocked" || event.status === "failed")
  ) {
    flags.integrityHaltSeen = true;
  }

  // Control-plane events (pause/resume/cancel) target `watchdog` but do not
  // mean the pipeline actually advanced past every earlier stage, so they
  // must never trigger the structural backfill below.
  if (event.event_type.startsWith("control_")) return;

  const index = CORE_LOOP_ORDER.indexOf(targetId);
  if (index <= 0) return;
  // LangGraph nodes run strictly in sequence within one experiment iteration
  // (orchestration/graph.py): once a later core-loop stage has reported
  // activity, any earlier stage still marked "running" has synchronously
  // returned, i.e. it succeeded, even though the backend does not emit an
  // explicit terminal event for every stage.
  for (let i = 0; i < index; i++) {
    const priorState = states[CORE_LOOP_ORDER[i]];
    if (priorState.status === "running") priorState.status = "succeeded";
  }
}

export function deriveNodeStates(events: RunEventDTO[]): Record<string, NodeRuntimeState> {
  const ordered = [...events].sort((left, right) => left.sequence - right.sequence);
  // A new `knowledge_mcp` "started" event is the iteration boundary
  // (AGENTS.md #6): everything before the latest one belongs to a prior
  // iteration whose non-Data card statuses must not leak into this one.
  const boundaryEvent = [...ordered].reverse().find((event) => event.component_id === "knowledge_mcp" && event.event_type === "started");
  const currentIterationStart = boundaryEvent?.sequence ?? -Infinity;

  // Data-group cards reflect the full session history: they represent
  // session-level state, not one experiment iteration, so every historical
  // event is replayed for them regardless of iteration boundaries.
  const dataStates = idleStates();
  const dataFlags = { integrityHaltSeen: false };
  for (const event of ordered) {
    if (!PERSISTENT_DATA_NODES[uiNodeIdForEvent(event)]) continue;
    applyEvent(dataStates, event, dataFlags);
  }
  // A baseline safety failure (orchestration/graph.py `baseline()`, the
  // tolerance-miss branch) never emits a terminal `trainer`/"baseline" event
  // -- only the phase_guard integrity halt fires. Infer that the still-
  // "running" baseline card stopped, without fabricating a fake event.
  if (dataStates.initial_baseline.status === "running" && dataFlags.integrityHaltSeen) {
    dataStates.initial_baseline.status = "failed";
  }

  // Every other card resets to "waiting" at each iteration boundary and is
  // only ever replayed from the current iteration's events, so a proxy
  // failure or a stale "Succeeded"/"Blocked" label from a prior experiment
  // never leaks into the next one. Historical events for these nodes still
  // live in `events`/History via the full session projection below.
  const iterationStates = idleStates();
  const iterationFlags = { integrityHaltSeen: false };
  for (const event of ordered) {
    if (event.sequence < currentIterationStart) continue;
    if (PERSISTENT_DATA_NODES[uiNodeIdForEvent(event)]) continue;
    applyEvent(iterationStates, event, iterationFlags);
  }

  // History must show every historical event for every node (AGENTS.md #6:
  // "preserve every historical event in state.events" / "preserve the
  // History detail section"), even for cards whose *current* status
  // projection was just reset. Replay the full session into a parallel
  // "history" pass and graft only the `events` arrays from it onto the
  // reset projection, leaving `status`/`startedAt` from the iteration-scoped
  // pass untouched.
  const historyStates = idleStates();
  const historyFlags = { integrityHaltSeen: false };
  for (const event of ordered) {
    if (PERSISTENT_DATA_NODES[uiNodeIdForEvent(event)]) continue;
    applyEvent(historyStates, event, historyFlags);
  }

  const states: Record<string, NodeRuntimeState> = {};
  for (const node of NODES) {
    if (PERSISTENT_DATA_NODES[node.id]) {
      states[node.id] = dataStates[node.id];
    } else {
      states[node.id] = { ...iterationStates[node.id], events: historyStates[node.id].events };
    }
  }
  return states;
}

export function nodeStatusMap(states: Record<string, NodeRuntimeState>): Record<string, NodeStatus> {
  return Object.fromEntries(Object.entries(states).map(([id, state]) => [id, state.status]));
}

export function eventsForNode(states: Record<string, NodeRuntimeState>, nodeId: string): RunEventDTO[] {
  return states[nodeId]?.events ?? [];
}
