import { EDGES, NODES, NodeStatus } from "../data/nodeRegistry";
import { laneColorFor, NODE_H, NODE_W, Vec2 } from "./laneData";
import { edgePoint, bezierPath, bezierPoint } from "./edgeMath";

interface Props {
  positions: Record<string, Vec2>;
  nodeStatus: Record<string, NodeStatus>;
  nodeElapsed: Record<string, number>;
  reducedMotion: boolean;
}

export function EdgesLayer({ positions, nodeStatus, nodeElapsed, reducedMotion }: Props) {
  const edges = EDGES.map(([from, to], index) => {
    const isDashed = from === "trainer" && to === "recovery";
    const p1 = edgePoint(positions[from], "right", NODE_W, NODE_H);
    const p2 = edgePoint(positions[to], "left", NODE_W, NODE_H);
    const { d, midX } = bezierPath(p1, p2);
    const fromDone = nodeStatus[from] === "succeeded";
    const toActive = nodeStatus[to] === "running" || nodeStatus[to] === "succeeded";
    const active = fromDone && toActive && !isDashed;
    const fromNode = NODES.find((node) => node.id === from)!;
    const toNode = NODES.find((node) => node.id === to)!;
    const fromColor = laneColorFor(fromNode).b;
    const toColor = laneColorFor(toNode).b;
    return { from, to, index, d, p1, p2, midX, isDashed, active, fromColor, toColor };
  });

  const runningId = Object.keys(nodeStatus).find((id) => nodeStatus[id] === "running");
  const cometPoints: Array<{ x: number; y: number; r: number; opacity: number }> = [];

  if (runningId && !reducedMotion) {
    const incoming = edges.find((edge) => edge.to === runningId);
    if (incoming) {
      const loopMs = 950;
      const elapsed = nodeElapsed[runningId] || 0;
      const steps = 5;
      for (let i = 0; i < steps; i++) {
        const tRaw = elapsed - i * 90;
        const t = ((tRaw % loopMs) + loopMs) % loopMs / loopMs;
        const point = bezierPoint(incoming.p1, incoming.p2, incoming.midX, t);
        const fade = 1 - i / steps;
        cometPoints.push({ x: point.x, y: point.y, r: 2 + fade * 3.5, opacity: 0.14 + fade * 0.62 });
      }
    }
  }

  return (
    <svg className="workflow-edges" width={1} height={1} aria-hidden="true">
      <defs>
        {edges.map((edge) => (
          <linearGradient key={`gradient-${edge.index}`} id={`edge-gradient-${edge.index}`} gradientUnits="userSpaceOnUse" x1={edge.p1.x} y1={edge.p1.y} x2={edge.p2.x} y2={edge.p2.y}>
            <stop offset="0" stopColor={edge.fromColor} />
            <stop offset="1" stopColor={edge.toColor} />
          </linearGradient>
        ))}
        <linearGradient id="edge-gradient-flow" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="var(--flow-a)" />
          <stop offset="1" stopColor="var(--flow-b)" />
        </linearGradient>
        <filter id="signal-soft" x="-100%" y="-100%" width="300%" height="300%">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {edges.map((edge) => {
        const stroke = edge.isDashed ? "#9ba7b6" : edge.active ? "url(#edge-gradient-flow)" : `url(#edge-gradient-${edge.index})`;
        const arrowColor = edge.active ? "var(--flow-b)" : edge.toColor;
        return (
          <g key={`${edge.from}-${edge.to}`} className={`workflow-edge ${edge.active ? "is-active" : ""}`}>
            <path className="workflow-edge__bed" d={edge.d} fill="none" />
            <path
              className="workflow-edge__line"
              d={edge.d}
              stroke={stroke}
              fill="none"
              strokeDasharray={edge.isDashed ? "4 7" : edge.active ? "9 8" : "2.5 7"}
            />
            <circle className="workflow-edge__port" cx={edge.p1.x} cy={edge.p1.y} r={3.4} fill={edge.fromColor} />
            <circle className="workflow-edge__port" cx={edge.p2.x} cy={edge.p2.y} r={3.4} fill={edge.toColor} />
            {!edge.isDashed && (
              <g
                className="workflow-edge__arrow"
                style={{ transformOrigin: `${edge.p2.x}px ${edge.p2.y}px`, animationDelay: `${(edge.index % 6) * 260}ms` }}
              >
                <path
                  d={`M ${edge.p2.x - 9.5} ${edge.p2.y - 4.6} L ${edge.p2.x - 1} ${edge.p2.y} L ${edge.p2.x - 9.5} ${edge.p2.y + 4.6} Z`}
                  fill={arrowColor}
                />
              </g>
            )}
          </g>
        );
      })}

      {[...cometPoints].reverse().map((point, i) => (
        <circle
          key={i}
          cx={point.x}
          cy={point.y}
          r={point.r}
          fill="var(--flow-b)"
          opacity={point.opacity}
          filter={i === cometPoints.length - 1 ? "url(#signal-soft)" : undefined}
        />
      ))}
    </svg>
  );
}
