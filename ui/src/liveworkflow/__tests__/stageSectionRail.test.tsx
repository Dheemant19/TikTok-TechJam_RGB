import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { NODES, type NodeStatus } from "../../data/nodeRegistry";
import type { RunEventDTO } from "../../api/types";
import { computeInitialPositions } from "../laneData";
import { StageFocusView } from "../StageFocusView";
import { useRunStore } from "../runStore";

// jsdom has neither `Element.scrollIntoView` nor `IntersectionObserver` --
// `StageDetailScroller` uses both (AGENTS.md #2's `scrollToSection` and the
// manual-scroll active-section observer respectively).
beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  class MockIntersectionObserver {
    observe = vi.fn();
    disconnect = vi.fn();
    unobserve = vi.fn();
  }
  // @ts-expect-error -- jsdom stub, not the real browser API
  global.IntersectionObserver = MockIntersectionObserver;
});

afterEach(() => {
  cleanup();
  useRunStore.setState({ events: [] });
});

const positions = computeInitialPositions();
const nodeStatus: Record<string, NodeStatus> = Object.fromEntries(NODES.map((n) => [n.id, "waiting" as NodeStatus]));

function renderStage(nodeId: string, overrides: Partial<Parameters<typeof StageFocusView>[0]> = {}) {
  const onNavigate = vi.fn();
  const onClose = vi.fn();
  const { container } = render(
    <StageFocusView
      nodeId={nodeId}
      previousNodeId={null}
      phase="open"
      overlayOpen
      overlayRect={{ left: 10, top: 10, width: 200, height: 120 }}
      positions={positions}
      nodeStatus={nodeStatus}
      nodeElapsed={{}}
      reducedMotion={false}
      isNarrow={false}
      onClose={onClose}
      onNavigate={onNavigate}
      {...overrides}
    />,
  );
  return { onNavigate, onClose, container };
}

function watchdogRejectEvent(): RunEventDTO {
  return {
    event_id: "evt-1",
    session_id: "s1",
    run_id: "r1",
    sequence: 1,
    component_id: "watchdog",
    execution_id: "exec-1",
    stage: "decide",
    event_type: "frontier",
    status: "rejected",
    occurred_at: new Date().toISOString(),
    plain_summary: "Rejected the candidate",
    payload: { decision: "reject" },
    artifact_ids: [],
    previous_event_hash: null,
    event_hash: "hash-1",
  };
}

describe("stage detail vertical section rail (AGENTS.md #2)", () => {
  it("renders all four sections as real buttons with Summary active by default", () => {
    renderStage("scientist");
    const nav = screen.getByRole("navigation", { name: "Stage detail sections" });
    const labels = within(nav).getAllByRole("button", { name: /^(Summary|Input|Output|History)$/ });
    expect(labels.map((el) => el.textContent)).toEqual(["Summary", "Input", "Output", "History"]);
    expect(within(nav).getByRole("button", { name: "Summary" })).toHaveAttribute("aria-current", "location");
  });

  it("does not render section chevrons inside the floating title navigation", () => {
    renderStage("scientist");
    const nav = screen.getByRole("navigation", { name: "Stage detail sections" });
    expect(within(nav).queryByRole("button", { name: /previous section|next section|no previous|no next/i })).not.toBeInTheDocument();
  });

  it("clicking a section label scrolls to it and moves the active accent, without touching process-card navigation", () => {
    const { onNavigate } = renderStage("scientist");
    const nav = screen.getByRole("navigation", { name: "Stage detail sections" });
    fireEvent.click(within(nav).getByRole("button", { name: "Input" }));
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith(expect.objectContaining({ behavior: "smooth", block: "start" }));
    expect(within(nav).getByRole("button", { name: "Input" })).toHaveAttribute("aria-current", "location");
    expect(within(nav).getByRole("button", { name: "Summary" })).not.toHaveAttribute("aria-current");
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("uses an instant jump (no smooth scroll) under reduced motion", () => {
    renderStage("scientist", { reducedMotion: true });
    const nav = screen.getByRole("navigation", { name: "Stage detail sections" });
    fireEvent.click(within(nav).getByRole("button", { name: "Output" }));
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith(expect.objectContaining({ behavior: "auto", block: "start" }));
  });

  it("ArrowDown/Home/End move focus and selection through the four sections", () => {
    renderStage("scientist");
    const nav = screen.getByRole("navigation", { name: "Stage detail sections" });
    const summary = within(nav).getByRole("button", { name: "Summary" });
    summary.focus();
    fireEvent.keyDown(summary, { key: "ArrowDown" });
    expect(within(nav).getByRole("button", { name: "Input" })).toHaveAttribute("aria-current", "location");
    expect(within(nav).getByRole("button", { name: "Input" })).toHaveFocus();

    fireEvent.keyDown(within(nav).getByRole("button", { name: "Input" }), { key: "End" });
    expect(within(nav).getByRole("button", { name: "History" })).toHaveAttribute("aria-current", "location");
    expect(within(nav).getByRole("button", { name: "History" })).toHaveFocus();

    fireEvent.keyDown(within(nav).getByRole("button", { name: "History" }), { key: "Home" });
    expect(within(nav).getByRole("button", { name: "Summary" })).toHaveAttribute("aria-current", "location");
    expect(within(nav).getByRole("button", { name: "Summary" })).toHaveFocus();
  });

  it("Escape still closes the stage view when it bubbles past the rail", () => {
    const { onClose } = renderStage("scientist");
    const nav = screen.getByRole("navigation", { name: "Stage detail sections" });
    fireEvent.keyDown(within(nav).getByRole("button", { name: "Summary" }), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("points Continue-to at Find Research Evidence after a rejected watchdog decision, and Save Run Evidence otherwise", () => {
    useRunStore.setState({ events: [watchdogRejectEvent()] });
    let { container } = renderStage("watchdog");
    let continueControl = container.querySelector(".stage-detail__continue");
    expect(continueControl?.textContent).toContain("Find Research Evidence");
    expect(continueControl?.textContent).not.toContain("Save Run Evidence");

    cleanup();
    useRunStore.setState({ events: [] });
    ({ container } = renderStage("watchdog"));
    continueControl = container.querySelector(".stage-detail__continue");
    expect(continueControl?.textContent).toContain("Save Run Evidence");
  });
});
