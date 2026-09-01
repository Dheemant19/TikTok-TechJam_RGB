import { useMemo } from "react";
import { EDGES, LOOP_EDGES, NODES, NodeStatus } from "../data/nodeRegistry";
import { laneColorFor, loopClearanceY, NODE_H, NODE_W, Vec2 } from "./laneData";
import { edgePoint, bezierPath, loopPath } from "./edgeMath";
import { useRunStore } from "./runStore";

interface Props {
  positions: Record<string, Vec2>;
  // `nodeStatus`/`nodeElapsed` are kept so both call sites (LiveWorkflowCanvas,
  // FocusArchitecturePane) can keep passing the same props they already
  // compute -- the single active-transition edge below now reads
  // `activeTransitionEdge` off the run store directly instead of deriving it
  // from per-node status, since that store field is topology-aware (it knows
  // about the rejected-decision loop) in a way a plain status diff isn't.
  nodeStatus: Record<string, NodeStatus>;
  nodeElapsed: Record<string, number>;
  reducedMotion: boolean;
}

/** The signal stays visible long enough to read as a handoff, while remaining
 * shorter than a routine stage change. Native SVG motion keeps it smooth
 * without driving a React render on every animation frame. */
const TRANSITION_DURATION_MS = 1500;

export function EdgesLayer({ positions, nodeStatus: _nodeStatus, nodeElapsed: _nodeElapsed, reducedMotion }: Props) {
  const activeTransitionEdge = useRunStore((s) => s.activeTransitionEdge);

  const edges = useMemo(
    () =>
      EDGES.map(([from, to], index) => {
        const isDashed = from === "trainer" && to === "recovery";
        const p1 = edgePoint(positions[from], "right", NODE_W, NODE_H);
        const p2 = edgePoint(positions[to], "left", NODE_W, NODE_H);
        const { d, midX } = bezierPath(p1, p2);
        const isActive = !!activeTransitionEdge && !activeTransitionEdge.isLoop && activeTransitionEdge.from === from && activeTransitionEdge.to === to;
        const fromNode = NODES.find((node) => node.id === from)!;
        const toNode = NODES.find((node) => node.id === to)!;
        const fromColor = laneColorFor(fromNode).b;
        const toColor = laneColorFor(toNode).b;
        return { from, to, index, d, p1, p2, midX, isDashed, isActive, fromColor, toColor };
      }),
    [positions, activeTransitionEdge],
  );

  // A rejected decision exits from the watchdog's left edge and returns to
  // the top edge of Find Research Evidence. This endpoint pair makes the
  // return path visibly terminate at that card instead of appearing to feed
  // through it into Choose the Next Experiment.
  const loopEdges = useMemo(() => {
    return LOOP_EDGES.map(([from, to], index) => {
      const p1: Vec2 = {
        x: positions[from].x,
        y: positions[from].y + NODE_H / 2,
      };
      const p2: Vec2 = {
        x: positions[to].x + NODE_W / 2,
        y: positions[to].y,
      };
      const clearanceY = loopClearanceY(positions, from, to);
      const { d } = loopPath(p1, p2, clearanceY);
      const isActive = !!activeTransitionEdge && activeTransitionEdge.isLoop && activeTransitionEdge.from === from && activeTransitionEdge.to === to;
      const fromNode = NODES.find((node) => node.id === from)!;
      const toNode = NODES.find((node) => node.id === to)!;
      return { from, to, index, d, p1, p2, isActive, fromColor: laneColorFor(fromNode).b, toColor: laneColorFor(toNode).b };
    });
  }, [positions, activeTransitionEdge]);

  const activeTracker = useMemo(() => {
    if (!activeTransitionEdge || reducedMotion) return null;
    const collection = activeTransitionEdge.isLoop ? loopEdges : edges;
    const edge = collection.find(
      (candidate) => candidate.from === activeTransitionEdge.from && candidate.to === activeTransitionEdge.to,
    );
    return edge ? { d: edge.d, token: activeTransitionEdge.token, color: edge.toColor } : null;
  }, [activeTransitionEdge, edges, loopEdges, reducedMotion]);

  return (
    <svg className="workflow-edges" width={1} height={1} aria-hidden="true">
      <defs>
        {edges.map((edge) => (
          <linearGradient key={`gradient-${edge.index}`} id={`edge-gradient-${edge.index}`} gradientUnits="userSpaceOnUse" x1={edge.p1.x} y1={edge.p1.y} x2={edge.p2.x} y2={edge.p2.y}>
            <stop offset="0" stopColor={edge.fromColor} />
            <stop offset="1" stopColor={edge.toColor} />
          </linearGradient>
        ))}
        {loopEdges.map((edge) => (
          <linearGradient key={`loop-gradient-${edge.index}`} id={`loop-gradient-${edge.index}`} gradientUnits="userSpaceOnUse" x1={edge.p1.x} y1={edge.p1.y} x2={edge.p2.x} y2={edge.p2.y}>
            <stop offset="0" stopColor={edge.fromColor} />
            <stop offset="1" stopColor={edge.toColor} />
          </linearGradient>
        ))}
      </defs>

      {edges.map((edge) => {
        const stroke = edge.isDashed ? "#9ba7b6" : `url(#edge-gradient-${edge.index})`;
        const arrowColor = edge.toColor;
        return (
          <g key={`${edge.from}-${edge.to}`} className={`workflow-edge ${edge.isActive ? "is-flowing" : ""}`}>
            <path className="workflow-edge__bed" d={edge.d} fill="none" />
            <path
              className="workflow-edge__line"
              d={edge.d}
              stroke={stroke}
              fill="none"
              strokeDasharray={edge.isDashed ? "4 7" : edge.isActive ? "9 8" : "2.5 7"}
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

      {loopEdges.map((edge) => {
        const stroke = `url(#loop-gradient-${edge.index})`;
        const arrowColor = edge.toColor;
        return (
          <g key={`loop-${edge.from}-${edge.to}`} className={`workflow-edge workflow-loop-edge ${edge.isActive ? "is-flowing" : ""}`}>
            <path className="workflow-edge__bed" d={edge.d} fill="none" />
            <path className="workflow-edge__line" d={edge.d} stroke={stroke} fill="none" strokeDasharray={edge.isActive ? "9 8" : "5 8"} />
            <circle className="workflow-edge__port" cx={edge.p1.x} cy={edge.p1.y} r={3.4} fill={edge.fromColor} />
            <circle className="workflow-edge__port" cx={edge.p2.x} cy={edge.p2.y} r={3.4} fill={edge.toColor} />
            <g className="workflow-edge__arrow" style={{ transformOrigin: `${edge.p2.x}px ${edge.p2.y}px` }}>
              <path
                d={`M ${edge.p2.x - 4.6} ${edge.p2.y - 10.5} L ${edge.p2.x} ${edge.p2.y - 2} L ${edge.p2.x + 4.6} ${edge.p2.y - 10.5} Z`}
                fill={arrowColor}
              />
            </g>
          </g>
        );
      })}

      {activeTracker && (
        <path
          key={activeTracker.token}
          className="workflow-edge-tracker"
          d={activeTracker.d}
          pathLength={100}
          fill="none"
          stroke={activeTracker.color}
          strokeDasharray="10 100"
          strokeDashoffset="0"
          strokeLinecap="round"
        >
          <animate
            attributeName="stroke-dashoffset"
            from="0"
            to="-100"
            dur={`${TRANSITION_DURATION_MS}ms`}
            fill="freeze"
            calcMode="spline"
            keyTimes="0;1"
            keySplines="0.22 1 0.36 1"
          />
        </path>
      )}
    </svg>
  );
}
