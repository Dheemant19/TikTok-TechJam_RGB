import { describe, expect, it } from "vitest";
import type { RunEventDTO } from "../../api/types";
import { deriveNodeStates } from "../eventMapping";

function event(
  sequence: number,
  componentId: string,
  stage: string,
  eventType: string,
  status: RunEventDTO["status"],
): RunEventDTO {
  return {
    event_id: `event-${sequence}`,
    session_id: "session-1",
    run_id: "run-1",
    sequence,
    component_id: componentId,
    execution_id: `execution-${sequence}`,
    stage,
    event_type: eventType,
    status,
    occurred_at: `2026-08-30T10:00:0${sequence}Z`,
    plain_summary: eventType,
    payload: {},
    artifact_ids: [],
    previous_event_hash: null,
    event_hash: `hash-${sequence}`,
  };
}

describe("data-safety status projection", () => {
  it("keeps Check Data Safety waiting while the initial baseline is running", () => {
    const states = deriveNodeStates([
      event(1, "data_profiler", "data", "completed", "succeeded"),
      event(2, "trainer", "baseline", "started", "running"),
    ]);

    expect(states.initial_baseline.status).toBe("running");
    expect(states.phase_guard.status).toBe("waiting");
  });

  it("keeps Check Data Safety succeeded after successful baseline sanity checks", () => {
    const states = deriveNodeStates([
      event(1, "data_profiler", "data", "completed", "succeeded"),
      event(2, "trainer", "baseline", "started", "running"),
      event(3, "trainer", "baseline", "completed", "succeeded"),
      event(4, "phase_guard", "baseline", "sanity_checks", "succeeded"),
    ]);

    expect(states.phase_guard.status).toBe("succeeded");
    expect(states.initial_baseline.status).toBe("succeeded");
  });

  it("shows Check Data Safety running while baseline controls execute", () => {
    const states = deriveNodeStates([
      event(1, "data_profiler", "data", "completed", "succeeded"),
      event(2, "trainer", "baseline", "completed", "succeeded"),
      event(3, "phase_guard", "baseline", "sanity_checks", "running"),
    ]);

    expect(states.initial_baseline.status).toBe("succeeded");
    expect(states.phase_guard.status).toBe("running");
    expect(states.knowledge_mcp.status).toBe("waiting");
  });

  it("marks Check Data Safety blocked only for a real integrity halt", () => {
    const states = deriveNodeStates([
      event(1, "data_profiler", "data", "completed", "succeeded"),
      event(2, "trainer", "baseline", "started", "running"),
      event(3, "phase_guard", "baseline", "integrity_halt", "blocked"),
    ]);

    expect(states.phase_guard.status).toBe("blocked");
    expect(states.initial_baseline.status).toBe("failed");
  });
});
