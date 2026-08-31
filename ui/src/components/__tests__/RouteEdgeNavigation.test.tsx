import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { RouteEdgeNavigation } from "../RouteEdgeNavigation";

function CurrentPath() {
  return <output aria-label="Current path">{useLocation().pathname}</output>;
}

function renderNavigation(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <RouteEdgeNavigation />
      <CurrentPath />
    </MemoryRouter>,
  );
}

afterEach(cleanup);

describe("page-edge tab navigation", () => {
  it("moves to the adjacent application tabs", () => {
    renderNavigation("/data-profile");

    fireEvent.click(screen.getByRole("button", { name: "Next tab: Experiments" }));
    expect(screen.getByLabelText("Current path")).toHaveTextContent("/experiments");

    fireEvent.click(screen.getByRole("button", { name: "Previous tab: Data Profile" }));
    expect(screen.getByLabelText("Current path")).toHaveTextContent("/data-profile");
  });

  it("wraps from the Autonomy Log to Live Workflow", () => {
    renderNavigation("/autonomy");

    fireEvent.click(screen.getByRole("button", { name: "Next tab: Live Workflow" }));
    expect(screen.getByLabelText("Current path")).toHaveTextContent("/");
  });
});
