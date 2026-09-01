import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The store must never touch the real network/EventSource in a test -- every
// entry point it calls on `../api/client` is mocked here (AGENTS.md #9's
// regression scenario: "old session selected -> click Start Run -> new
// session returned -> new session is selected and marked running").
vi.mock("../../api/client", () => ({
  api: {
    listSessions: vi.fn(),
    startSession: vi.fn(),
    getSnapshot: vi.fn(),
    getReplay: vi.fn(),
    getExecution: vi.fn(),
    getArtifact: vi.fn(),
    control: vi.fn(),
    packageSession: vi.fn(),
    deleteSession: vi.fn(),
  },
  subscribeToEvents: vi.fn(),
}));

import { api, subscribeToEvents } from "../../api/client";
import type { RunEventDTO, SessionSnapshotDTO } from "../../api/types";
import { useRunStore } from "../runStore";

function makeSnapshot(sessionId: string): SessionSnapshotDTO {
  return {
    session_id: sessionId,
    latest_sequence: 0,
    status: "running",
    component_states: {},
    allowed_actions: [],
    current_run_id: null,
    metrics: {},
    frontier: {
      validation_best: null,
      stable_fallback: null,
      accepted_parent: null,
      pending_candidate: null,
      rejected: [],
      failed: [],
      no_improvement_count: 0,
      locked: false,
    },
    finalized: false,
    cancelled: false,
    manual_interventions: 0,
  };
}

function makeCancelledSnapshot(sessionId: string): SessionSnapshotDTO {
  return {
    ...makeSnapshot(sessionId),
    latest_sequence: 1,
    status: "failed",
    cancelled: true,
  };
}

function makeCoderStartedEvent(sessionId: string): RunEventDTO {
  return {
    event_id: "event-coder-started",
    session_id: sessionId,
    run_id: "run-1",
    sequence: 1,
    component_id: "coder",
    execution_id: "code-1",
    stage: "code",
    event_type: "started",
    status: "running",
    occurred_at: new Date().toISOString(),
    plain_summary: "Code Agent started",
    payload: {},
    artifact_ids: [],
    previous_event_hash: null,
    event_hash: "hash-coder-started",
  };
}

describe("session-picker race (AGENTS.md #9)", () => {
  const oldSessionId = "old-session-1";
  const newSessionId = "new-session-2";

  beforeEach(() => {
    vi.clearAllMocks();
    // Fresh store between tests -- detach() resets sessionId/sessions/error
    // and tears down the previous test's ticking interval and SSE stream.
    useRunStore.getState().detach();
    // Never invokes onEvent/onConnectionChange -- the race fix must not
    // depend on any live event actually arriving.
    vi.mocked(subscribeToEvents).mockReturnValue(() => {});
  });

  afterEach(() => {
    useRunStore.getState().detach();
  });

  it("old session selected -> Start Run -> new session returned -> new session is selected and marked running", async () => {
    // Simulate an old run already attached/selected, e.g. restored on page load.
    vi.mocked(api.getSnapshot).mockImplementation((sessionId: string) => Promise.resolve(makeSnapshot(sessionId)));
    await useRunStore.getState().attach(oldSessionId);
    expect(useRunStore.getState().sessionId).toBe(oldSessionId);

    vi.mocked(api.startSession).mockResolvedValue({ session_id: newSessionId, snapshot_url: `/api/v1/sessions/${newSessionId}/snapshot` });
    // The server's own list briefly lags behind session creation -- it may
    // not even contain the brand-new session yet when startRun() reads it.
    vi.mocked(api.listSessions).mockResolvedValue([
      { session_id: oldSessionId, status: "succeeded", created_at: new Date().toISOString(), latest_sequence: 5, finalized: 1, cancelled: 0 },
    ]);

    await useRunStore.getState().startRun();

    const state = useRunStore.getState();
    expect(state.sessionId).toBe(newSessionId);
    expect(state.sessionId).not.toBe(oldSessionId);
    expect(state.sessions.some((session) => session.session_id === newSessionId && session.status === "running")).toBe(true);
  });

  it("starts KuaiRand-1K with its isolated challenge config", async () => {
    useRunStore.getState().setSelectedBenchmark("kuairand_1k");
    vi.mocked(api.startSession).mockResolvedValue({
      session_id: newSessionId,
      snapshot_url: `/api/v1/sessions/${newSessionId}/snapshot`,
    });
    vi.mocked(api.getSnapshot).mockResolvedValue(makeSnapshot(newSessionId));
    vi.mocked(api.listSessions).mockResolvedValue([]);

    await useRunStore.getState().startRun();

    expect(api.startSession).toHaveBeenCalledWith(
      "configs/challenge/kuairand_1k.yaml",
      "configs/budgets/competition.yaml",
    );
    expect(useRunStore.getState().sessionId).toBe(newSessionId);
  });


  it("shows the real error and leaves the old session selected when startSession fails", async () => {
    vi.mocked(api.getSnapshot).mockImplementation((sessionId: string) => Promise.resolve(makeSnapshot(sessionId)));
    await useRunStore.getState().attach(oldSessionId);

    const failure = new Error("backend refused: budget exhausted");
    vi.mocked(api.startSession).mockRejectedValue(failure);

    await useRunStore.getState().startRun();

    const state = useRunStore.getState();
    // Must not claim the new session started: selection stays on the old,
    // still-valid session and the real error is surfaced.
    expect(state.sessionId).toBe(oldSessionId);
    expect(state.error).toBe(failure.message);
  });

  it("marks the active stage stopped when cancelled history is replayed", async () => {
    let replayEvent: ((event: RunEventDTO) => void) | undefined;
    vi.mocked(api.getSnapshot).mockResolvedValue(makeCancelledSnapshot(oldSessionId));
    vi.mocked(subscribeToEvents).mockImplementation((_sessionId, _sequence, onEvent) => {
      replayEvent = onEvent;
      return () => {};
    });

    await useRunStore.getState().attach(oldSessionId);
    replayEvent?.(makeCoderStartedEvent(oldSessionId));

    const state = useRunStore.getState();
    expect(state.snapshot?.cancelled).toBe(true);
    expect(state.nodeStatus.coder).toBe("failed");
    expect(state.nodeStates.coder.startedAt).toBeNull();
    expect(state.nodeStates.coder.events[state.nodeStates.coder.events.length - 1]?.plain_summary).toBe(
      "Session cancelled; active work stopped",
    );
  });

  it("updates the session picker immediately after cancel", async () => {
    const running = makeSnapshot(oldSessionId);
    const cancelled = makeCancelledSnapshot(oldSessionId);
    vi.mocked(api.getSnapshot)
      .mockResolvedValueOnce(running)
      .mockResolvedValueOnce(cancelled);
    vi.mocked(api.control).mockResolvedValue({ accepted: true, action: "cancel" });

    await useRunStore.getState().attach(oldSessionId);
    useRunStore.setState({
      sessions: [
        {
          session_id: oldSessionId,
          status: "running",
          created_at: new Date().toISOString(),
          latest_sequence: 0,
          finalized: 0,
          cancelled: 0,
        },
      ],
    });

    await useRunStore.getState().cancelRun();

    expect(useRunStore.getState().sessions[0]).toMatchObject({
      session_id: oldSessionId,
      status: "failed",
      latest_sequence: 1,
      cancelled: 1,
    });
  });
});
