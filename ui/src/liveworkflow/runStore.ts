import { create } from "zustand";
import { api, subscribeToEvents } from "../api/client";
import type { JsonRecord, RunEventDTO, SessionListItem, SessionSnapshotDTO } from "../api/types";
import { NODES, type NodeStatus } from "../data/nodeRegistry";
import { deriveNodeStates, nodeStatusMap, type NodeRuntimeState } from "./eventMapping";

// Matches configs/ui/observer.yaml `frontend.default_challenge_config` /
// `default_budget_config`. The observer API server resolves these relative
// to the repository root it was launched from (`serve-ui`).
const DEFAULT_CHALLENGE_CONFIG = "configs/challenge/kuairand_pure.yaml";
const DEFAULT_BUDGET_CONFIG = "configs/budgets/competition.yaml";
const SESSION_STORAGE_KEY = "rigor-rs.session-id";

export type ConnectionPhase = "idle" | "connecting" | "live" | "retrying" | "error";

function idleNodeStatus(): Record<string, NodeStatus> {
  return Object.fromEntries(NODES.map((node) => [node.id, "waiting" as NodeStatus]));
}

let syntheticSequence = -1;
function syntheticEvent(componentId: string, status: NodeStatus, summary: string, payload: JsonRecord = {}): RunEventDTO {
  syntheticSequence -= 1;
  return {
    event_id: `local-${componentId}-${syntheticSequence}`,
    session_id: "local",
    run_id: "local",
    sequence: syntheticSequence,
    component_id: componentId,
    execution_id: `local-${componentId}`,
    stage: "package",
    event_type: "local_outcome",
    status,
    occurred_at: new Date().toISOString(),
    plain_summary: summary,
    payload,
    artifact_ids: [],
    previous_event_hash: null,
    event_hash: `local-${componentId}-${syntheticSequence}`,
  };
}

/**
 * `finalizer`/`submission` are built from the `package` REST call's actual
 * response, not from a ledger event -- the backend only appends an event for
 * each of the 14 `COMPONENT_IDS` when its own pipeline stage runs, and
 * packaging is a separate one-way action invoked from the UI (Plan_UI.md
 * #5.4). This overlays that real outcome onto the derived per-node states
 * without fabricating any metric or ledger data.
 */
function withPackagingOverlay(
  states: Record<string, NodeRuntimeState>,
  packaging: boolean,
  packageResult: JsonRecord | null,
  packageError: string | null,
  canPackage: boolean,
): Record<string, NodeRuntimeState> {
  const finalizer = states.finalizer;
  const submission = states.submission;
  if (packageResult) {
    return {
      ...states,
      finalizer: { status: "succeeded", startedAt: null, events: [...finalizer.events, syntheticEvent("finalizer", "succeeded", "Final package built and schema-checked", packageResult)] },
      submission: { status: "succeeded", startedAt: null, events: [...submission.events, syntheticEvent("submission", "succeeded", "Predictions written and schema-verified", packageResult)] },
    };
  }
  if (packageError) {
    return { ...states, finalizer: { status: "failed", startedAt: null, events: [...finalizer.events, syntheticEvent("finalizer", "failed", packageError)] } };
  }
  if (packaging) {
    return { ...states, finalizer: { status: "running", startedAt: new Date().toISOString(), events: finalizer.events } };
  }
  if (canPackage && finalizer.status === "waiting") {
    return { ...states, finalizer: { ...finalizer, status: "ready" } };
  }
  return states;
}

interface RunState {
  sessionId: string | null;
  phase: ConnectionPhase;
  snapshot: SessionSnapshotDTO | null;
  events: RunEventDTO[];
  nodeStates: Record<string, NodeRuntimeState>;
  nodeStatus: Record<string, NodeStatus>;
  nodeElapsed: Record<string, number>;
  error: string | null;
  packaging: boolean;
  packageResult: JsonRecord | null;
  packageError: string | null;
  sessions: SessionListItem[];
  refreshSessions: () => Promise<void>;
  bootstrap: () => Promise<void>;
  startRun: () => Promise<void>;
  attach: (sessionId: string) => Promise<void>;
  detach: () => void;
  pauseRun: () => Promise<void>;
  resumeRun: () => Promise<void>;
  cancelRun: () => Promise<void>;
  packageRun: () => Promise<void>;
}

let closeStream: (() => void) | null = null;
let tickIntervalHandle: number | undefined;

interface DerivedNodeState {
  nodeStates: Record<string, NodeRuntimeState>;
  nodeStatus: Record<string, NodeStatus>;
}

function recomputeDerived(get: () => RunState): DerivedNodeState {
  const { events, snapshot, packaging, packageResult, packageError } = get();
  const baseStates = deriveNodeStates(events);
  const canPackage = snapshot?.allowed_actions.includes("package") ?? false;
  const nodeStates = withPackagingOverlay(baseStates, packaging, packageResult, packageError, canPackage);
  return { nodeStates, nodeStatus: nodeStatusMap(nodeStates) };
}

function startTicking(set: (partial: Partial<RunState>) => void, get: () => RunState): void {
  window.clearInterval(tickIntervalHandle);
  tickIntervalHandle = window.setInterval(() => {
    const { nodeStates, nodeElapsed } = get();
    const nextElapsed: Record<string, number> = { ...nodeElapsed };
    let changed = false;
    for (const [id, state] of Object.entries(nodeStates)) {
      if (state.status === "running" && state.startedAt) {
        nextElapsed[id] = Date.now() - new Date(state.startedAt).getTime();
        changed = true;
      }
    }
    if (changed) set({ nodeElapsed: nextElapsed });
  }, 200);
}

export const useRunStore = create<RunState>((set, get) => ({
  sessionId: null,
  phase: "idle",
  snapshot: null,
  events: [],
  nodeStates: deriveNodeStates([]),
  nodeStatus: idleNodeStatus(),
  nodeElapsed: {},
  error: null,
  packaging: false,
  packageResult: null,
  packageError: null,
  sessions: [],

  refreshSessions: async () => {
    try {
      set({ sessions: await api.listSessions() });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) });
    }
  },

  bootstrap: async () => {
    const remembered = window.localStorage.getItem(SESSION_STORAGE_KEY);
    try {
      const sessions = await api.listSessions();
      set({ sessions });
      const openSession = sessions.find((session) => session.finalized === 0 && session.cancelled === 0);
      const target = remembered && sessions.some((session) => session.session_id === remembered) ? remembered : (openSession ?? sessions[0])?.session_id;
      if (target) await get().attach(target);
    } catch (error) {
      set({ phase: "error", error: error instanceof Error ? error.message : String(error) });
    }
  },

  startRun: async () => {
    set({ phase: "connecting", error: null });
    try {
      const { session_id } = await api.startSession(DEFAULT_CHALLENGE_CONFIG, DEFAULT_BUDGET_CONFIG);
      await get().attach(session_id);
    } catch (error) {
      set({ phase: "error", error: error instanceof Error ? error.message : String(error) });
    }
  },

  attach: async (sessionId) => {
    closeStream?.();
    closeStream = null;
    window.localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
    set({
      sessionId,
      phase: "connecting",
      error: null,
      events: [],
      nodeStates: deriveNodeStates([]),
      nodeStatus: idleNodeStatus(),
      nodeElapsed: {},
      snapshot: null,
      packageResult: null,
      packageError: null,
      packaging: false,
    });
    try {
      set({ snapshot: await api.getSnapshot(sessionId) });
    } catch (error) {
      set({ phase: "error", error: error instanceof Error ? error.message : String(error), sessionId: null });
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
      return;
    }
    startTicking(set, get);
    closeStream = subscribeToEvents(
      sessionId,
      0,
      (event) => {
        const current = get().events;
        if (current.some((existing) => existing.sequence === event.sequence)) return;
        const events = [...current, event].sort((a, b) => a.sequence - b.sequence);
        set({ events, phase: "live" });
        set(recomputeDerived(get));
        api
          .getSnapshot(sessionId)
          .then((snapshot) => {
            set({ snapshot });
            set(recomputeDerived(get));
          })
          .catch(() => undefined);
      },
      (connectionState) => {
        if (connectionState === "open") set({ phase: "live" });
        else if (connectionState === "retrying") set({ phase: "retrying" });
        else set({ phase: "error", error: "Live updates disconnected" });
      },
    );
  },

  detach: () => {
    closeStream?.();
    closeStream = null;
    window.clearInterval(tickIntervalHandle);
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    set({
      sessionId: null,
      phase: "idle",
      snapshot: null,
      events: [],
      nodeStates: deriveNodeStates([]),
      nodeStatus: idleNodeStatus(),
      nodeElapsed: {},
      error: null,
      packageResult: null,
      packageError: null,
      packaging: false,
    });
  },

  pauseRun: async () => {
    const { sessionId, snapshot } = get();
    if (!sessionId || !snapshot) return;
    try {
      await api.control(sessionId, "pause", snapshot.latest_sequence);
      set({ snapshot: await api.getSnapshot(sessionId) });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) });
    }
  },
  resumeRun: async () => {
    const { sessionId, snapshot } = get();
    if (!sessionId || !snapshot) return;
    try {
      await api.control(sessionId, "resume", snapshot.latest_sequence);
      set({ snapshot: await api.getSnapshot(sessionId) });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) });
    }
  },
  cancelRun: async () => {
    const { sessionId, snapshot } = get();
    if (!sessionId || !snapshot) return;
    try {
      await api.control(sessionId, "cancel", snapshot.latest_sequence);
      set({ snapshot: await api.getSnapshot(sessionId) });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) });
    }
  },
  packageRun: async () => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ packaging: true, packageError: null });
    set(recomputeDerived(get));
    try {
      const result = await api.packageSession(sessionId);
      set({ packaging: false, packageResult: result });
    } catch (error) {
      set({ packaging: false, packageError: error instanceof Error ? error.message : String(error) });
    }
    set(recomputeDerived(get));
  },
}));
