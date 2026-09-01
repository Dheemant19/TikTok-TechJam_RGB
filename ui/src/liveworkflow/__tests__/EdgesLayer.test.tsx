import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EdgesLayer } from "../EdgesLayer";
import { NODE_H, NODE_W, computeInitialPositions } from "../laneData";


describe("rejected-decision connector", () => {
  it("runs from watchdog left edge to research evidence top edge", () => {
    const positions = computeInitialPositions();
    const { container } = render(
      <EdgesLayer
        positions={positions}
        nodeStatus={{}}
        nodeElapsed={{}}
        reducedMotion
      />,
    );
    const ports = container.querySelectorAll(".workflow-loop-edge .workflow-edge__port");
    expect(ports).toHaveLength(2);
    expect(ports[0].getAttribute("cx")).toBe(String(positions.watchdog.x));
    expect(ports[0].getAttribute("cy")).toBe(String(positions.watchdog.y + NODE_H / 2));
    expect(ports[1].getAttribute("cx")).toBe(String(positions.knowledge_mcp.x + NODE_W / 2));
    expect(ports[1].getAttribute("cy")).toBe(String(positions.knowledge_mcp.y));
  });
});
