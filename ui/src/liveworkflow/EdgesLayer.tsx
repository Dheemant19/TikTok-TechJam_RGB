import { EDGES, NodeStatus } from "../data/nodeRegistry";
import { NODE_H, NODE_W, Vec2 } from "./laneData";
import { edgePoint, bezierPath, bezierPoint } from "./edgeMath";

interface Props {
  positions: Record<string, Vec2>;
  nodeStatus: Record<string, NodeStatus>;
  nodeElapsed: Record<string, number>;
  reducedMotion: boolean;
}

export function EdgesLayer({ positions, nodeStatus, nodeElapsed, reducedMotion }: Props) {
  const edges = EDGES.map(([from, to]) => {
    const isDashed = from === "trainer" && to === "recovery";
    const p1 = edgePoint(positions[from], "right", NODE_W, NODE_H);
    const p2 = edgePoint(positions[to], "left", NODE_W, NODE_H);
    const { d, midX } = bezierPath(p1, p2);
    const fromDone = nodeStatus[from] === "succeeded";
    const toActive = nodeStatus[to] === "running" || nodeStatus[to] === "succeeded";
    const active = fromDone && toActive && !isDashed;
    const color = active ? "#3b82f6" : isDashed ? "#94a3b8" : "#64748b";
    return {
      from,
      to,
      d,
      p1,
      p2,
      midX,
      stroke: color,
      width: active ? 2.6 : 1.8,
      dasharray: isDashed ? "5 5" : active ? "10 6" : "none",
      animated: active && !reducedMotion,
    };
  });

  const runningId = Object.keys(nodeStatus).find((id) => nodeStatus[id] === "running");
  let tracker: { r: number; cx: number; cy: number; r2: number; cx2?: number; cy2?: number } = { r: 0, cx: -100, cy: -100, r2: 0 };
  if (runningId && !reducedMotion) {
    const inEdge = edges.find((e) => e.to === runningId);
    if (inEdge) {
      const loopMs = 750;
      const elapsed = nodeElapsed[runningId] || 0;
      const t = (elapsed % loopMs) / loopMs;
      const tTail = ((elapsed - 90 + loopMs) % loopMs) / loopMs;
      const head = bezierPoint(inEdge.p1, inEdge.p2, inEdge.midX, t);
      const tail = bezierPoint(inEdge.p1, inEdge.p2, inEdge.midX, tTail);
      tracker = { r: 8, cx: head.x, cy: head.y, r2: 5, cx2: tail.x, cy2: tail.y };
    }
  }

  return (
    <svg style={{ position: "absolute", left: 0, top: 0, overflow: "visible", pointerEvents: "none" }} width={1} height={1}>
      {edges.map((edge) => (
        <g key={`${edge.from}-${edge.to}`}>
          <path
            d={edge.d}
            stroke={edge.stroke}
            strokeWidth={edge.width}
            fill="none"
            strokeDasharray={edge.dasharray}
            strokeLinecap="round"
            style={edge.animated ? { animation: "dashFlow .7s linear infinite" } : undefined}
          />
          <circle cx={edge.p1.x} cy={edge.p1.y} r={4.5} fill={edge.stroke} />
          <circle cx={edge.p2.x} cy={edge.p2.y} r={4.5} fill={edge.stroke} />
        </g>
      ))}
      {tracker.cx2 !== undefined && <circle cx={tracker.cx2} cy={tracker.cy2} r={tracker.r2} fill="#fbbf24" opacity={0.55} />}
      {tracker.r > 0 && (
        <circle
          cx={tracker.cx}
          cy={tracker.cy}
          r={tracker.r}
          fill="#f59e0b"
          style={{ filter: "drop-shadow(0 0 10px rgba(245,158,11,1)) drop-shadow(0 0 4px rgba(255,255,255,.9))" }}
        />
      )}
    </svg>
  );
}
