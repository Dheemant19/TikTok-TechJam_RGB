import { describe, expect, it } from "vitest";
import type { RunEventDTO } from "../../api/types";
import { selectAutonomyTimeline } from "../selectors";

function planEvent(): RunEventDTO {
  return {
    event_id: "event-1",
    session_id: "session-1",
    run_id: "run-deepfm",
    sequence: 1,
    component_id: "scientist",
    execution_id: "research-1",
    stage: "research",
    event_type: "plan",
    status: "succeeded",
    occurred_at: "2026-08-30T10:00:01Z",
    plain_summary: "One bounded experiment selected",
    payload: {
      contract: {
        method_family: "deepfm",
        implementation_kind: "architecture",
        iteration_strategy: "tune_current_model",
        primary_change: "reduce the learning rate to stabilize late batches",
        decision_rationale: "Validation improved while the final batches oscillated.",
      },
    },
    artifact_ids: [],
    previous_event_hash: null,
    event_hash: "hash-1",
  };
}

describe("autonomy experiment decisions", () => {
  it("shows the selected model, iteration strategy, evidence, and concrete change", () => {
    const [row] = selectAutonomyTimeline([planEvent()]);

    expect(row.method).toBe("deepfm · tune current model");
    expect(row.action).toBe(
      "Validation improved while the final batches oscillated. Change: reduce the learning rate to stabilize late batches",
    );
  });

  it("shows the model and NVIDIA device observed during training", () => {
    const runtimeEvent: RunEventDTO = {
      ...planEvent(),
      event_id: "event-2",
      sequence: 2,
      component_id: "trainer",
      execution_id: "execute-2",
      stage: "execute",
      event_type: "tier4",
      plain_summary: "Full-scale din training on NVIDIA GeForce RTX 5060 Laptop GPU; 124909 validation rows scored",
      payload: {
        training: {
          model_family: "din",
          device: "cuda:0",
          device_name: "NVIDIA GeForce RTX 5060 Laptop GPU",
          observed_gpu_seconds: 6.2,
          observed_gpu_devices: ["NVIDIA GeForce RTX 5060 Laptop GPU"],
        },
      },
    };

    const [row] = selectAutonomyTimeline([runtimeEvent]);

    expect(row.method).toBe("din · NVIDIA GeForce RTX 5060 Laptop GPU");
    expect(row.action).toContain("124909 validation rows scored");
  });
});
