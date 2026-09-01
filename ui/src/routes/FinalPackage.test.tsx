import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { JsonRecord, RunEventDTO, SessionSnapshotDTO } from "../api/types";
import { useRunStore } from "../liveworkflow/runStore";
import { FinalPackage } from "./FinalPackage";

const SESSION_ID = "session-finalized";

function snapshot(): SessionSnapshotDTO {
  return {
    session_id: SESSION_ID,
    latest_sequence: 4,
    status: "succeeded",
    component_states: {},
    allowed_actions: [],
    current_run_id: null,
    metrics: {},
    frontier: {
      validation_best: "B0",
      stable_fallback: "B0",
      accepted_parent: "B0",
      pending_candidate: null,
      rejected: ["run-1", "run-2"],
      failed: [],
      no_improvement_count: 3,
      locked: true,
    },
    finalized: true,
    cancelled: false,
    manual_interventions: 0,
  };
}

function event(sequence: number, runId: string, predictionHash: string): RunEventDTO {
  return {
    event_id: `event-${sequence}`,
    session_id: SESSION_ID,
    run_id: runId,
    sequence,
    component_id: "evaluator",
    execution_id: `execution-${sequence}`,
    stage: "validation",
    event_type: "metric",
    status: "succeeded",
    occurred_at: "2026-08-31T00:00:00Z",
    plain_summary: "Official validation metrics recorded",
    payload: {
      metrics: { GAUC: 0.66, "nDCG@5": 0.53, primary: 0.595 },
      receipt: { prediction_artifact_id: predictionHash },
    },
    artifact_ids: [],
    previous_event_hash: null,
    event_hash: `hash-${sequence}`,
  };
}

function packageResult(): JsonRecord {
  return {
    validation_best: "B0",
    experiment_id: null,
    predictions: `C:\\artifacts\\final\\${SESSION_ID}\\predictions.csv`,
    checkpoint: "C:\\artifacts\\baseline\\fm_seed_0.npz",
    manifest_hash: "manifest-hash",
    event_chain_valid: true,
    schema_check: { exit_code: 0 },
  };
}

afterEach(() => {
  cleanup();
  useRunStore.getState().detach();
});

describe("FinalPackage verdict", () => {
  it("warns that a finalized session with duplicate experiment outputs must not be submitted", () => {
    useRunStore.setState({
      sessionId: SESSION_ID,
      snapshot: snapshot(),
      packageResult: packageResult(),
      events: [event(1, "run-1", "same-predictions"), event(2, "run-2", "same-predictions")],
    });

    render(
      <MemoryRouter>
        <FinalPackage />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Package blocked by an integrity warning" })).toBeTruthy();
    expect(screen.getByText(/byte-identical outputs from 2 experiment runs/i)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Download predictions.csv" })).toBeNull();
    expect(screen.getByRole("link", { name: "Return to Live Workflow" }).getAttribute("href")).toBe("/");
  });

  it("states plainly that a valid B0 package is not a winning result", () => {
    useRunStore.setState({
      sessionId: SESSION_ID,
      snapshot: snapshot(),
      packageResult: packageResult(),
      events: [event(1, "run-1", "unique-predictions")],
    });

    render(
      <MemoryRouter>
        <FinalPackage />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Baseline package ready" })).toBeTruthy();
    expect(screen.getByText("Not scored here")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Download predictions.csv" }).getAttribute("href"),
    ).toBe(`/api/v1/sessions/${SESSION_ID}/package/predictions.csv`);
  });

  it("builds the attached session without requiring typed confirmation", () => {
    const readySnapshot = snapshot();
    readySnapshot.finalized = false;
    readySnapshot.frontier.locked = true;
    readySnapshot.allowed_actions = ["package"];
    const packageRun = vi.fn(async () => undefined);
    useRunStore.setState({
      sessionId: SESSION_ID,
      snapshot: readySnapshot,
      packageResult: null,
      packageRun,
      events: [],
    });

    render(
      <MemoryRouter>
        <FinalPackage />
      </MemoryRouter>,
    );

    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Build final package" }));
    expect(packageRun).toHaveBeenCalledOnce();
  });

  it("unlocks packaging from terminal frontier facts when allowed_actions is briefly stale", () => {
    const staleSnapshot = snapshot();
    staleSnapshot.finalized = false;
    staleSnapshot.status = "succeeded";
    staleSnapshot.frontier.locked = true;
    staleSnapshot.frontier.validation_best = "B0";
    staleSnapshot.allowed_actions = [];
    const packageRun = vi.fn(async () => undefined);
    useRunStore.setState({
      sessionId: SESSION_ID,
      snapshot: staleSnapshot,
      events: [],
      packageResult: null,
      packageError: null,
      packaging: false,
      packageRun,
    });

    render(
      <MemoryRouter>
        <FinalPackage />
      </MemoryRouter>,
    );

    const button = screen.getByRole("button", { name: "Build final package" });
    expect((button as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(button);
    expect(packageRun).toHaveBeenCalledOnce();
  });
});
