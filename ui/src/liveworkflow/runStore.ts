import { create } from "zustand";
import { asRecord, field } from "../api/json";
import { api, subscribeToEvents } from "../api/client";
import type { JsonRecord, RunEventDTO, SessionListItem, SessionSnapshotDTO } from "../api/types";
import { EDGES, NODES, type NodeStatus } from "../data/nodeRegistry";
import { deriveNodeStates, nodeStatusMap, uiNodeIdForEvent, type NodeRuntimeState } from "./eventMapping";

export const BENCHMARK_OPTIONS = [
  { id: "kuairand_pure", label: "KuaiRand-Pure", challengeConfig: "configs/challenge/kuairand_pure.yaml" },
  { id: "kuairand_1k", label: "KuaiRand-1K", challengeConfig: "configs/challenge/kuairand_1k.yaml" },
] as const;
export type BenchmarkId = (typeof BENCHMARK_OPTIONS)[number]["id"];
const DEFAULT_BUDGET_CONFIG = "configs/budgets/competition.yaml";
const SESSION_STORAGE_KEY = "flowstate.session-id";
const BENCHMARK_STORAGE_KEY = "flowstate.benchmark";

function initialBenchmark(): BenchmarkId {
  const stored = window.localStorage.getItem(BENCHMARK_STORAGE_KEY);
  return BENCHMARK_OPTIONS.some((option) => option.id === stored)
    ? stored as BenchmarkId
    : "kuairand_pure";
}

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

/**
 * Event replay can end on a stage's historical "started" event. Once the
 * server says the session was cancelled, no card may keep presenting that
 * stale event as active work.
 */
function withCancelledSessionOverlay(
  states: Record<string, NodeRuntimeState>,
  cancelled: boolean,
): Record<string, NodeRuntimeState> {
  if (!cancelled) return states;
  return Object.fromEntries(
    Object.entries(states).map(([nodeId, state]) => [
      nodeId,
      state.status === "running"
        ? {
            ...state,
            status: "failed" as NodeStatus,
            startedAt: null,
            events: [
              ...state.events,
              syntheticEvent(nodeId, "failed", "Session cancelled; active work stopped"),
            ],
          }
        : state,
    ]),
  );
}

/** A single transient, UI-only highlighted edge (AGENTS.md "Improve idle and
 * active workflow-edge animation" -- exactly one edge may be highlighted as
 * the current transition at any point, shared by the main canvas and the
 * stage-focus architecture pane since both read it off this store). */
export interface ActiveTransitionEdge {
  from: string;
  to: string;
  /** Distinguishes the rejected-decision backward loop from a forward edge. */
  isLoop: boolean;
  /** Monotonic id; a consumer must ignore a stale clear scheduled for an
   * already-superseded transition. */
  token: number;
  /** `Date.now()` when the transition started, for a deterministic
   * requestAnimationFrame progress clock (never `elapsed % loopMs`). */
  startedAt: number;
}

/** A UI-generated monitoring notice for a stage that has been running past
 * the AGENTS.md #10 five-minute threshold. Never a fabricated `RunEventDTO`
 * -- stored and rendered separately from real ledger events. */
export interface ObserverNotice {
  id: string;
  nodeId: string;
  componentLabel: string;
  createdAt: string;
  elapsedMs: number;
  stage: string | null;
  eventType: string | null;
  summary: string | null;
  stillRunning: boolean;
}

const LONG_RUNNING_THRESHOLD_MS = 300_000;
const TRANSITION_DURATION_MS = 1500;

function upsertObserverNotices(sessionId: string, nodeStates: Record<string, NodeRuntimeState>, existing: ObserverNotice[]): ObserverNotice[] {
  const next = [...existing];
  for (const node of NODES) {
    const state = nodeStates[node.id];
    if (!state) continue;
    const isRunning = state.status === "running" && state.startedAt !== null;
    const elapsedMs = isRunning ? Date.now() - new Date(state.startedAt as string).getTime() : 0;
    const lastEvent = state.events[state.events.length - 1];
    const noticeId = `${sessionId}:${node.id}:${lastEvent?.execution_id ?? state.startedAt ?? "none"}`;
    const noticeIndex = next.findIndex((notice) => notice.id === noticeId);
    if (isRunning && elapsedMs >= LONG_RUNNING_THRESHOLD_MS) {
      next[noticeIndex >= 0 ? noticeIndex : next.length] = {
        id: noticeId,
        nodeId: node.id,
        componentLabel: node.label,
        createdAt: noticeIndex >= 0 ? next[noticeIndex].createdAt : new Date().toISOString(),
        elapsedMs,
        stage: lastEvent?.stage ?? null,
        eventType: lastEvent?.event_type ?? null,
        summary: lastEvent?.plain_summary ?? null,
        stillRunning: true,
      };
    } else if (noticeIndex >= 0 && next[noticeIndex].stillRunning && !isRunning) {
      // The stage finished after crossing the threshold: update its status
      // in place rather than deleting the historical notice (AGENTS.md #10).
      next[noticeIndex] = { ...next[noticeIndex], stillRunning: false };
    }
  }
  return next;
}

/**
 * A meaningful transition is a specific new (non-control-plane) event
 * changing its mapped node's displayed status, resolved against the visible
 * topology (AGENTS.md "Edge transition detection": graph topology and real
 * state changes, never "all previous nodes succeeded", polling, duplicates,
 * or control events). `knowledge_mcp` restarting is only ever the drawn
 * backward loop when it follows a rejected watchdog decision (AGENTS.md #5)
 * -- a "retain" continuation restarts research too, but has no drawn edge in
 * this topology, so it intentionally lights nothing rather than the
 * misleading stale baseline->research edge.
 */
function detectTransitionEdge(
  previousStatus: Record<string, NodeStatus>,
  nextStatus: Record<string, NodeStatus>,
  event: RunEventDTO,
  priorEvents: RunEventDTO[],
): { from: string; to: string; isLoop: boolean } | null {
  if (event.event_type.startsWith("control_")) return null;
  const targetId = uiNodeIdForEvent(event);
  if (nextStatus[targetId] === previousStatus[targetId]) return null;

  const isFirstKnowledgeMcpEvent = !priorEvents.some((candidate) => candidate.component_id === "knowledge_mcp" && candidate.event_type === "started");
  if (targetId === "knowledge_mcp" && !isFirstKnowledgeMcpEvent) {
    const priorDecisionEvent = [...priorEvents].reverse().find((candidate) => candidate.component_id === "watchdog" && candidate.event_type === "frontier");
    const decision = priorDecisionEvent ? field(asRecord(priorDecisionEvent.payload), "decision") : null;
    return decision === "reject" ? { from: "watchdog", to: "knowledge_mcp", isLoop: true } : null;
  }

  const incomingEdge = EDGES.find(([, to]) => to === targetId);
  return incomingEdge ? { from: incomingEdge[0], to: incomingEdge[1], isLoop: false } : null;
}

interface RunState {
  sessionId: string | null;
  selectedBenchmark: BenchmarkId;
  phase: ConnectionPhase;
  snapshot: SessionSnapshotDTO | null;
  events: RunEventDTO[];
  nodeStates: Record<string, NodeRuntimeState>;
  nodeStatus: Record<string, NodeStatus>;
  nodeElapsed: Record<string, number>;
  activeTransitionEdge: ActiveTransitionEdge | null;
  observerNotices: ObserverNotice[];
  error: string | null;
  packaging: boolean;
  packageResult: JsonRecord | null;
  packageError: string | null;
  sessions: SessionListItem[];
  refreshSessions: () => Promise<void>;
  setSelectedBenchmark: (benchmark: BenchmarkId) => void;
  bootstrap: () => Promise<void>;
  startRun: () => Promise<void>;
  attach: (sessionId: string) => Promise<void>;
  detach: () => void;
  deleteSession: () => Promise<void>;
  pauseRun: () => Promise<void>;
  resumeRun: () => Promise<void>;
  cancelRun: () => Promise<void>;
  packageRun: () => Promise<void>;
}

let closeStream: (() => void) | null = null;
let tickIntervalHandle: number | undefined;
let replayThroughSequence = 0;
let transitionTokenCounter = 0;
let transitionClearHandle: number | undefined;

interface DerivedNodeState {
  nodeStates: Record<string, NodeRuntimeState>;
  nodeStatus: Record<string, NodeStatus>;
}

function snapshotCanPackage(snapshot: SessionSnapshotDTO | null): boolean {
  if (!snapshot || snapshot.finalized || snapshot.cancelled) return false;
  if (snapshot.allowed_actions.includes("package")) return true;
  // A terminal SSE event can arrive one render before the follow-up snapshot
  // request. Use the same facts the backend enforces so the package card does
  // not remain disabled because that one read was briefly stale.
  return snapshot.status === "succeeded"
    && snapshot.frontier.locked
    && Boolean(snapshot.frontier.validation_best);
}

function recomputeDerived(get: () => RunState): DerivedNodeState {
  const { events, snapshot, packaging, packageResult, packageError } = get();
  const replayedStates = deriveNodeStates(events);
  const baseStates = withCancelledSessionOverlay(replayedStates, snapshot?.cancelled ?? false);
  const canPackage = snapshotCanPackage(snapshot);
  const nodeStates = withPackagingOverlay(baseStates, packaging, packageResult, packageError, canPackage);
  return { nodeStates, nodeStatus: nodeStatusMap(nodeStates) };
}

function computeElapsed(nodeStates: Record<string, NodeRuntimeState>): Record<string, number> {
  const nextElapsed: Record<string, number> = {};
  for (const [id, state] of Object.entries(nodeStates)) {
    nextElapsed[id] = state.status === "running" && state.startedAt ? Date.now() - new Date(state.startedAt).getTime() : 0;
  }
  return nextElapsed;
}

function startTicking(set: (partial: Partial<RunState>) => void, get: () => RunState): void {
  window.clearInterval(tickIntervalHandle);
  tickIntervalHandle = window.setInterval(() => {
    const { nodeStates, sessionId, observerNotices } = get();
    const nodeElapsed = computeElapsed(nodeStates);
    if (!sessionId) {
      set({ nodeElapsed });
      return;
    }
    set({ nodeElapsed, observerNotices: upsertObserverNotices(sessionId, nodeStates, observerNotices) });
  }, 200);
}

/** Builds the optimistic session-list entry inserted the instant a new
 * session id is known, before the server's own list has caught up
 * (AGENTS.md #9: the dropdown must never keep showing the previous run). */
function optimisticSession(sessionId: string): SessionListItem {
  return { session_id: sessionId, status: "running", created_at: new Date().toISOString(), latest_sequence: 0, finalized: 0, cancelled: 0 };
}

export const useRunStore = create<RunState>((set, get) => ({
  sessionId: null,
  selectedBenchmark: initialBenchmark(),
  phase: "idle",
  snapshot: null,
  events: [],
  nodeStates: deriveNodeStates([]),
  nodeStatus: idleNodeStatus(),
  nodeElapsed: {},
  activeTransitionEdge: null,
  observerNotices: [],
  error: null,
  packaging: false,
  packageResult: null,
  packageError: null,
  sessions: [],

  setSelectedBenchmark: (benchmark) => {
    window.localStorage.setItem(BENCHMARK_STORAGE_KEY, benchmark);
    set({ selectedBenchmark: benchmark });
  },
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
      const selected = BENCHMARK_OPTIONS.find(
        (option) => option.id === get().selectedBenchmark,
      ) ?? BENCHMARK_OPTIONS[0];
      const { session_id } = await api.startSession(selected.challengeConfig, DEFAULT_BUDGET_CONFIG);
      // Insert the optimistic entry and select it before the network round
      // trip to attach() even begins, so `<select value={sessionId}>` always
      // has a matching option (AGENTS.md #9) -- never wait on a server-list
      // refresh that may itself be briefly stale right after creation.
      const optimistic = optimisticSession(session_id);
      set((state) => ({ sessions: state.sessions.some((session) => session.session_id === session_id) ? state.sessions : [optimistic, ...state.sessions] }));
      await get().attach(session_id);
      // Refresh from the server afterward, but merge rather than replace:
      // `refreshSessions()`'s raw `set({ sessions: ... })` would otherwise
      // briefly overwrite the list with a server response that doesn't yet
      // contain the just-created session, dropping the optimistic entry for
      // one microtask before a separate patch step re-added it (AGENTS.md
      // #9 point 7: "Merge the refreshed list ... if the server response is
      // briefly stale" -- never a bare overwrite).
      api
        .listSessions()
        .then((refreshed) => {
          const hasNew = refreshed.some((session) => session.session_id === session_id);
          set({ sessions: hasNew ? refreshed : [optimistic, ...refreshed] });
        })
        .catch(() => undefined);
    } catch (error) {
      set({ phase: "error", error: error instanceof Error ? error.message : String(error) });
    }
  },

  attach: async (sessionId) => {
    closeStream?.();
    closeStream = null;
    window.clearTimeout(transitionClearHandle);
    window.localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
    set({
      sessionId,
      phase: "connecting",
      error: null,
      events: [],
      nodeStates: deriveNodeStates([]),
      nodeStatus: idleNodeStatus(),
      nodeElapsed: {},
      activeTransitionEdge: null,
      observerNotices: [],
      snapshot: null,
      packageResult: null,
      packageError: null,
      packaging: false,
    });
    try {
      const snapshot = await api.getSnapshot(sessionId);
      replayThroughSequence = snapshot.latest_sequence;
      set({ snapshot });
    } catch (error) {
      set({ phase: "error", error: error instanceof Error ? error.message : String(error), sessionId: null });
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
      return;
    }
    startTicking(set, get);
    replayThroughSequence = get().snapshot?.latest_sequence ?? 0;
    closeStream = subscribeToEvents(
      sessionId,
      0,
      (event) => {
        const priorEvents = get().events;
        if (priorEvents.some((existing) => existing.sequence === event.sequence)) return;
        const previousStatus = get().nodeStatus;
        const events = [...priorEvents, event].sort((a, b) => a.sequence - b.sequence);
        set({ events, phase: "live" });
        set(recomputeDerived(get));

        if (event.event_type === "finalized") {
          const manifest = asRecord(field(asRecord(event.payload), "manifest"));
          if (manifest) set({ packageResult: manifest, packageError: null });
        }
        if (event.sequence > replayThroughSequence) {
          const transition = detectTransitionEdge(previousStatus, get().nodeStatus, event, priorEvents);
          if (transition) {
            window.clearTimeout(transitionClearHandle);
            transitionTokenCounter += 1;
            const token = transitionTokenCounter;
            set({ activeTransitionEdge: { ...transition, token, startedAt: Date.now() } });
            transitionClearHandle = window.setTimeout(() => {
              set((state) => (state.activeTransitionEdge?.token === token ? { activeTransitionEdge: null } : {}));
            }, TRANSITION_DURATION_MS);
          }
        }

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
    window.clearTimeout(transitionClearHandle);
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    set({
      sessionId: null,
      phase: "idle",
      snapshot: null,
      events: [],
      nodeStates: deriveNodeStates([]),
      nodeStatus: idleNodeStatus(),
      nodeElapsed: {},
      activeTransitionEdge: null,
      observerNotices: [],
      error: null,
      packageResult: null,
      packageError: null,
      packaging: false,
    });
  },

  deleteSession: async () => {
    const { sessionId } = get();
    if (!sessionId) return;
    try {
      await api.deleteSession(sessionId);
      get().detach();
      set({ sessions: await api.listSessions(), error: null });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) });
      throw error;
    }
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
      const nextSnapshot = await api.getSnapshot(sessionId);
      set((state) => ({
        snapshot: nextSnapshot,
        sessions: state.sessions.map((session) =>
          session.session_id === sessionId
            ? {
                ...session,
                status: nextSnapshot.status,
                latest_sequence: nextSnapshot.latest_sequence,
                finalized: nextSnapshot.finalized ? 1 : 0,
                cancelled: nextSnapshot.cancelled ? 1 : 0,
              }
            : session,
        ),
      }));
      set(recomputeDerived(get));
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
