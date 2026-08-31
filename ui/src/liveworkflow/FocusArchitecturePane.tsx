import { useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { EDGES, GROUP_LABELS, GROUP_ORDER, LOOP_EDGES, NODES, type NodeStatus } from "../data/nodeRegistry";
import { contentBounds, laneColorFor, loopClearanceY, NODE_H, NODE_W, type Vec2 } from "./laneData";
import { EdgesLayer } from "./EdgesLayer";
import { FOCUS_NODE_H, FOCUS_NODE_W, NodeCard } from "./NodeCard";
import { useRunStore } from "./runStore";

interface Props {
  positions: Record<string, Vec2>;
  nodeStatus: Record<string, NodeStatus>;
  nodeElapsed: Record<string, number>;
  selectedNodeId: string;
  reducedMotion: boolean;
  interactive?: boolean;
  onSelectNode: (nodeId: string) => void;
}

interface SurfaceSize {
  width: number;
  height: number;
}

function FocusLaneScaffolds({ positions }: { positions: Record<string, Vec2> }) {
  return (
    <div className="focus-architecture__lanes" aria-hidden="true">
      {GROUP_ORDER.map((group) => {
        const nodes = NODES.filter((node) => node.group === group);
        const xs = nodes.map((node) => positions[node.id].x);
        const ys = nodes.map((node) => positions[node.id].y);
        const color = laneColorFor(nodes[0]);
        const style = {
          left: Math.min(...xs) - 22,
          top: Math.min(...ys) - 58,
          width: Math.max(...xs) - Math.min(...xs) + NODE_W + 44,
          height: Math.max(...ys) - Math.min(...ys) + NODE_H + 80,
          "--lane-rule": color.b,
        } as CSSProperties;
        return (
          <div key={group} className="focus-architecture__lane" style={style}>
            <strong>{GROUP_LABELS[group]}</strong>
          </div>
        );
      })}
    </div>
  );
}

export function FocusArchitecturePane({
  positions,
  nodeStatus,
  nodeElapsed,
  selectedNodeId,
  reducedMotion,
  interactive = true,
  onSelectNode,
}: Props) {
  const surfaceRef = useRef<HTMLDivElement>(null);
  const [surface, setSurface] = useState<SurfaceSize>({ width: 0, height: 0 });
  const bounds = useMemo(() => contentBounds(positions), [positions]);
  // The loop arch can legitimately peek above the tightest node bounds;
  // reserve exactly the room `EdgesLayer` will actually use (same helper),
  // rather than a fixed guess that either clips the arch or over-reserves.
  const visualMinY = Math.min(bounds.minY, ...LOOP_EDGES.map(([from, to]) => loopClearanceY(positions, from, to)));
  const boundsWidth = Math.max(1, bounds.maxX - bounds.minX);
  const boundsHeight = Math.max(1, bounds.maxY - visualMinY);
  const selectedNode = NODES.find((node) => node.id === selectedNodeId) ?? NODES[0];
  const activeTransitionEdge = useRunStore((state) => state.activeTransitionEdge);

  useLayoutEffect(() => {
    const element = surfaceRef.current;
    if (!element) return;
    const measure = () => {
      const rect = element.getBoundingClientRect();
      setSurface({ width: rect.width, height: rect.height });
    };
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const fitScale = surface.width && surface.height
    ? Math.min(0.86, Math.max(0.26, Math.min((surface.width - 58) / boundsWidth, (surface.height - 98) / boundsHeight)))
    : 0.42;
  const worldLeft = (surface.width - boundsWidth * fitScale) / 2 - bounds.minX * fitScale;
  const worldTop = (surface.height - boundsHeight * fitScale) / 2 - visualMinY * fitScale + 12;
  const focusWidth = Math.min(FOCUS_NODE_W, Math.max(268, surface.width - 32));
  const focusHeight = surface.width <= 720 ? 190 : FOCUS_NODE_H;
  const focusPosition = {
    x: Math.max(16, (surface.width - focusWidth) / 2),
    y: Math.max(18, (surface.height - focusHeight) / 2 + 8),
  };

  return (
    <div className="focus-architecture-pane" style={{ "--focus-pane-accent": laneColorFor(selectedNode).b } as CSSProperties}>
      <div className="focus-architecture__readout" aria-hidden="true">
        <span>Live architecture</span>
        <span className="mono">{NODES.length} nodes / {EDGES.length} links</span>
      </div>

      <div ref={surfaceRef} className="focus-architecture__surface">
        <div className="focus-architecture__context-layer">
          <div
            className="focus-architecture__world"
            style={{
              width: bounds.maxX,
              height: bounds.maxY,
              transform: `translate3d(${worldLeft}px, ${worldTop}px, 0) scale(${fitScale})`,
              transformOrigin: "0 0",
            }}
          >
            <FocusLaneScaffolds positions={positions} />
            <EdgesLayer positions={positions} nodeStatus={nodeStatus} nodeElapsed={nodeElapsed} reducedMotion={reducedMotion} />
            {NODES.map((node) => (
              <NodeCard
                key={node.id}
                node={node}
                position={positions[node.id]}
                status={nodeStatus[node.id] ?? "waiting"}
                elapsedMs={nodeElapsed[node.id] ?? 0}
                reducedMotion={reducedMotion}
                isDragging={false}
                isSelected={selectedNodeId === node.id}
                isArriving={activeTransitionEdge?.to === node.id}
                mode="context"
                interactive={interactive}
                onPointerDownCard={() => undefined}
                onOpen={() => {
                  if (interactive && selectedNodeId !== node.id) onSelectNode(node.id);
                }}
              />
            ))}
          </div>
        </div>

        <div className="focus-architecture__focus-layer">
          <NodeCard
            node={selectedNode}
            position={focusPosition}
            size={{ width: focusWidth, minHeight: focusHeight }}
            status={nodeStatus[selectedNodeId] ?? "waiting"}
            elapsedMs={nodeElapsed[selectedNodeId] ?? 0}
            reducedMotion={reducedMotion}
            isDragging={false}
            isSelected={false}
            mode="focus"
            isArriving={activeTransitionEdge?.to === selectedNode.id}
            interactive={interactive}
            onPointerDownCard={() => undefined}
            onOpen={() => {
              if (interactive) onSelectNode(selectedNodeId);
            }}
          />
        </div>
      </div>
    </div>
  );
}

