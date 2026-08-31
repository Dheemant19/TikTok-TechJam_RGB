import { useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { GROUP_LABELS, GROUP_ORDER, NODES } from "../data/nodeRegistry";
import { computeInitialPositions, contentBounds, laneColorFor, NODE_H, NODE_W, Vec2 } from "./laneData";
import { NodeCard } from "./NodeCard";
import { EdgesLayer } from "./EdgesLayer";
import { StageFocusView } from "./StageFocusView";
import { useRunStore } from "./runStore";
import { useFlipInspector } from "./useFlipInspector";
import { CanvasPulseField } from "../components/CanvasPulseField";

interface DragInfo {
  id: string;
  startX: number;
  startY: number;
  origX: number;
  origY: number;
  moved: boolean;
}
interface GroupDragInfo {
  group: string;
  startX: number;
  startY: number;
  origins: Record<string, Vec2>;
  moved: boolean;
}
interface PanInfo {
  startX: number;
  startY: number;
  origX: number;
  origY: number;
}

interface Props {
  reducedMotion: boolean;
  isNarrow: boolean;
  /** Multiplier: 0.5 = slower, 1 = default, 2 = faster. */
  idleEdgeSpeed?: number;
}

function LaneScaffold({
  positions,
  draggingGroup,
  onGroupPointerDown,
}: {
  positions: Record<string, Vec2>;
  draggingGroup: string | null;
  onGroupPointerDown: (group: string, e: ReactPointerEvent<HTMLDivElement>) => void;
}) {
  return (
    <div className="lane-scaffolds" aria-hidden="true">
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
          <div
            key={group}
            className={`lane-scaffold ${draggingGroup === group ? "is-dragging" : ""}`}
            style={style}
            onPointerDown={(e) => onGroupPointerDown(group, e)}
          >
            <strong>{GROUP_LABELS[group]}</strong>
          </div>
        );
      })}
    </div>
  );
}

export function LiveWorkflowCanvas({ reducedMotion, isNarrow, idleEdgeSpeed = 1 }: Props) {
  const [positions, setPositions] = useState<Record<string, Vec2>>(() => computeInitialPositions());
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [draggingGroup, setDraggingGroup] = useState<string | null>(null);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const {
    selectedId,
    previousNodeId,
    overlayRect,
    overlayOpen,
    phase,
    openNode,
    navigateNode,
    closeInspector,
  } = useFlipInspector(reducedMotion);
  const clampedIdleEdgeSpeed = Math.min(4, Math.max(0.25, idleEdgeSpeed));
  const canvasStyle = {
    "--idle-edge-duration": `${14 / clampedIdleEdgeSpeed}s`,
    "--idle-arrow-duration": `${3.6 / clampedIdleEdgeSpeed}s`,
  } as CSSProperties;

  const nodeStatus = useRunStore((s) => s.nodeStatus);
  const nodeElapsed = useRunStore((s) => s.nodeElapsed);
  const activeTransitionEdge = useRunStore((s) => s.activeTransitionEdge);

  const dragInfo = useRef<DragInfo | null>(null);
  const groupDragInfo = useRef<GroupDragInfo | null>(null);
  const suppressClick = useRef(false);
  const panInfo = useRef<PanInfo | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const panRef = useRef(pan);
  const zoomRef = useRef(zoom);
  const positionsRef = useRef(positions);
  panRef.current = pan;
  zoomRef.current = zoom;
  positionsRef.current = positions;

  // Recenter is a full view reset: return to 100% and then center the current
  // content bounds. The same behavior is used by the button and F shortcut.
  const recenter = useCallback(() => {
    const el = canvasRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const bounds = contentBounds(positionsRef.current);
    zoomRef.current = 1;
    setZoom(1);
    setPan({ x: rect.width / 2 - bounds.centerX, y: rect.height / 2 - bounds.centerY });
  }, []);

  // Center the pipeline in the viewport on first mount, instead of leaving it
  // anchored to the top-left corner (the transform's local origin).
  useEffect(() => {
    recenter();
  }, [recenter]);

  // "F" recenters the workflow, mirroring the mount-time centering, as long
  // as focus isn't inside a form control or the stage-focus dialog (where a
  // bare keystroke should type/act locally instead of panning the canvas).
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "f" && event.key !== "F") return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const active = document.activeElement;
      const tag = active?.tagName;
      const isFormField =
        tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || tag === "BUTTON" || (active instanceof HTMLElement && active.isContentEditable);
      const inDialog = active instanceof Element && active.closest('[role="dialog"]') !== null;
      if (isFormField || inDialog) return;
      event.preventDefault();
      recenter();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [recenter]);

  const handleDragMove = (e: PointerEvent) => {
    const info = dragInfo.current;
    if (!info) return;
    const dx = (e.clientX - info.startX) / zoom;
    const dy = (e.clientY - info.startY) / zoom;
    if (!info.moved) {
      if (Math.abs(dx) <= 4 && Math.abs(dy) <= 4) return;
      info.moved = true;
      setDraggingId(info.id);
    }
    setPositions((prev) => ({ ...prev, [info.id]: { x: info.origX + dx, y: info.origY + dy } }));
  };
  const handleDragUp = () => {
    window.removeEventListener("pointermove", handleDragMove);
    window.removeEventListener("pointerup", handleDragUp);
    if (dragInfo.current?.moved) {
      suppressClick.current = true;
      setTimeout(() => {
        suppressClick.current = false;
      }, 50);
    }
    dragInfo.current = null;
    setDraggingId(null);
  };
  const startDrag = (id: string, e: ReactPointerEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    dragInfo.current = { id, startX: e.clientX, startY: e.clientY, origX: positions[id].x, origY: positions[id].y, moved: false };
    window.addEventListener("pointermove", handleDragMove);
    window.addEventListener("pointerup", handleDragUp);
  };

  const handleGroupDragMove = (e: PointerEvent) => {
    const info = groupDragInfo.current;
    if (!info) return;
    const dx = (e.clientX - info.startX) / zoom;
    const dy = (e.clientY - info.startY) / zoom;
    if (!info.moved) {
      if (Math.abs(dx) <= 4 && Math.abs(dy) <= 4) return;
      info.moved = true;
      setDraggingGroup(info.group);
    }
    setPositions((prev) => {
      const next = { ...prev };
      for (const [id, origin] of Object.entries(info.origins)) {
        next[id] = { x: origin.x + dx, y: origin.y + dy };
      }
      return next;
    });
  };
  const handleGroupDragUp = () => {
    window.removeEventListener("pointermove", handleGroupDragMove);
    window.removeEventListener("pointerup", handleGroupDragUp);
    if (groupDragInfo.current?.moved) {
      suppressClick.current = true;
      setTimeout(() => {
        suppressClick.current = false;
      }, 50);
    }
    groupDragInfo.current = null;
    setDraggingGroup(null);
  };
  const startGroupDrag = (group: string, e: ReactPointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    const origins: Record<string, Vec2> = {};
    for (const node of NODES) {
      if (node.group === group) origins[node.id] = positions[node.id];
    }
    groupDragInfo.current = { group, startX: e.clientX, startY: e.clientY, origins, moved: false };
    window.addEventListener("pointermove", handleGroupDragMove);
    window.addEventListener("pointerup", handleGroupDragUp);
  };

  const handlePanMove = (e: PointerEvent) => {
    const info = panInfo.current;
    if (!info) return;
    setPan({ x: info.origX + (e.clientX - info.startX), y: info.origY + (e.clientY - info.startY) });
  };
  const handlePanUp = () => {
    window.removeEventListener("pointermove", handlePanMove);
    window.removeEventListener("pointerup", handlePanUp);
    panInfo.current = null;
  };
  const onCanvasPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) return;
    panInfo.current = { startX: e.clientX, startY: e.clientY, origX: pan.x, origY: pan.y };
    window.addEventListener("pointermove", handlePanMove);
    window.addEventListener("pointerup", handlePanUp);
  };
  useEffect(
    () => () => {
      window.removeEventListener("pointermove", handleDragMove);
      window.removeEventListener("pointerup", handleDragUp);
      window.removeEventListener("pointermove", handleGroupDragMove);
      window.removeEventListener("pointerup", handleGroupDragUp);
      window.removeEventListener("pointermove", handlePanMove);
      window.removeEventListener("pointerup", handlePanUp);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  // React attaches JSX onWheel as a passive listener, so preventDefault() would
  // silently fail there; a native listener with {passive:false} is required to
  // actually stop the page from scrolling while zooming the canvas.
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const zoomNow = zoomRef.current;
      const newZoom = Math.min(1.4, Math.max(0.55, zoomNow - e.deltaY * 0.001));
      const rect = el.getBoundingClientRect();
      // Zoom toward the cursor: keep the content point under the pointer fixed
      // on screen, so zooming out settles toward wherever you're looking
      // instead of drifting the pipeline toward the top-left corner.
      const pointerX = e.clientX - rect.left;
      const pointerY = e.clientY - rect.top;
      const localX = (pointerX - panRef.current.x) / zoomNow;
      const localY = (pointerY - panRef.current.y) / zoomNow;
      setPan({ x: pointerX - localX * newZoom, y: pointerY - localY * newZoom });
      setZoom(newZoom);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const handleOpen = (id: string, rect: DOMRect) => {
    if (suppressClick.current) return;
    openNode(id, { left: rect.left, top: rect.top, width: rect.width, height: rect.height });
  };

  return (
    <div className="workflow-canvas-shell">
      <div
        ref={canvasRef}
        className="workflow-canvas"
        style={canvasStyle}
        onPointerDown={onCanvasPointerDown}
      >
        <CanvasPulseField reducedMotion={reducedMotion} />
        <div className="workflow-world" style={{ position: "absolute", left: 0, top: 0, transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, transformOrigin: "0 0" }}>
          <LaneScaffold positions={positions} draggingGroup={draggingGroup} onGroupPointerDown={startGroupDrag} />
          <EdgesLayer positions={positions} nodeStatus={nodeStatus} nodeElapsed={nodeElapsed} reducedMotion={reducedMotion} />
          {NODES.map((node) => (
            <NodeCard
              key={node.id}
              node={node}
              position={positions[node.id]}
              status={nodeStatus[node.id]}
              elapsedMs={nodeElapsed[node.id] || 0}
              reducedMotion={reducedMotion}
              isDragging={draggingId === node.id || draggingGroup === node.group}
              isSelected={selectedId === node.id && overlayOpen}
              isArriving={activeTransitionEdge?.to === node.id}
              onPointerDownCard={(e) => startDrag(node.id, e)}
              onOpen={(rect) => handleOpen(node.id, rect)}
            />
          ))}
        </div>
      </div>

      <div className="workflow-canvas__hint" aria-hidden="true">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
          <path d="M5.2 6.5V4.3a1 1 0 0 1 2 0v1.3-2a1 1 0 1 1 2 0v2-1.1a1 1 0 1 1 2 0v1.9-.6a1 1 0 1 1 2 0v2.8c0 3.2-1.7 5.1-4.7 5.1H7.1c-1.5 0-2.5-.7-3.4-1.8L2 9.8a1.1 1.1 0 0 1 1.7-1.4l1.5 1.5V6.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Drag canvas · scroll to zoom · select a stage
      </div>

      <button
        type="button"
        className="workflow-canvas__recenter"
        onClick={recenter}
        title="Reset workflow view"
        aria-label="Reset workflow view to 100 percent"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <circle cx="8" cy="8" r="4.4" stroke="currentColor" strokeWidth="1.3" />
          <path d="M8 1.2v2.5M8 12.3v2.5M1.2 8h2.5M12.3 8h2.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
      </button>

      <div className="workflow-canvas__zoom tabular" aria-label={`Canvas zoom ${Math.round(zoom * 100)} percent`}>
        {Math.round(zoom * 100)}%
      </div>

      <StageFocusView
        nodeId={selectedId}
        previousNodeId={previousNodeId}
        phase={phase}
        overlayOpen={overlayOpen}
        overlayRect={overlayRect}
        positions={positions}
        nodeStatus={nodeStatus}
        nodeElapsed={nodeElapsed}
        reducedMotion={reducedMotion}
        isNarrow={isNarrow}
        onClose={closeInspector}
        onNavigate={navigateNode}
      />
    </div>
  );
}
