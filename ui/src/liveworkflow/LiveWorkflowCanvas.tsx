import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { NODES } from "../data/nodeRegistry";
import { computeInitialPositions, contentBounds, Vec2 } from "./laneData";
import { NodeCard } from "./NodeCard";
import { EdgesLayer } from "./EdgesLayer";
import { InspectorPanel } from "./InspectorPanel";
import { useRunStore } from "./runStore";
import { useFlipInspector } from "./useFlipInspector";

interface DragInfo {
  id: string;
  startX: number;
  startY: number;
  origX: number;
  origY: number;
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
}

export function LiveWorkflowCanvas({ reducedMotion, isNarrow }: Props) {
  const [positions, setPositions] = useState<Record<string, Vec2>>(() => computeInitialPositions());
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const { selectedId, overlayRect, overlayOpen, openNode, closeInspector } = useFlipInspector(reducedMotion);

  const nodeStatus = useRunStore((s) => s.nodeStatus);
  const nodeElapsed = useRunStore((s) => s.nodeElapsed);

  const dragInfo = useRef<DragInfo | null>(null);
  const panInfo = useRef<PanInfo | null>(null);
  const suppressClick = useRef(false);
  const canvasRef = useRef<HTMLDivElement>(null);
  const panRef = useRef(pan);
  const zoomRef = useRef(zoom);
  panRef.current = pan;
  zoomRef.current = zoom;

  // Center the pipeline in the viewport on first mount, instead of leaving it
  // anchored to the top-left corner (the transform's local origin).
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const bounds = contentBounds(positions);
    setPan({ x: rect.width / 2 - bounds.centerX, y: rect.height / 2 - bounds.centerY });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleDragMove = (e: PointerEvent) => {
    const info = dragInfo.current;
    if (!info) return;
    const dx = (e.clientX - info.startX) / zoom;
    const dy = (e.clientY - info.startY) / zoom;
    if (Math.abs(dx) > 4 || Math.abs(dy) > 4) info.moved = true;
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
  };
  const startDrag = (id: string, e: ReactPointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    dragInfo.current = { id, startX: e.clientX, startY: e.clientY, origX: positions[id].x, origY: positions[id].y, moved: false };
    window.addEventListener("pointermove", handleDragMove);
    window.addEventListener("pointerup", handleDragUp);
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
    <div style={{ position: "relative", flex: 1, minWidth: 0, overflow: "hidden" }}>
      <div
        ref={canvasRef}
        style={{ position: "absolute", inset: 0, cursor: "grab" }}
        onPointerDown={onCanvasPointerDown}
      >
        <div style={{ position: "absolute", left: 0, top: 0, transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, transformOrigin: "0 0" }}>
          <EdgesLayer positions={positions} nodeStatus={nodeStatus} nodeElapsed={nodeElapsed} reducedMotion={reducedMotion} />
          {NODES.map((node) => (
            <NodeCard
              key={node.id}
              node={node}
              position={positions[node.id]}
              status={nodeStatus[node.id]}
              elapsedMs={nodeElapsed[node.id] || 0}
              reducedMotion={reducedMotion}
              onPointerDownCard={(e) => startDrag(node.id, e)}
              onOpen={(rect) => handleOpen(node.id, rect)}
            />
          ))}
        </div>
      </div>

      <InspectorPanel
        nodeId={selectedId}
        status={selectedId ? nodeStatus[selectedId] : "waiting"}
        overlayRect={overlayRect}
        overlayOpen={overlayOpen}
        reducedMotion={reducedMotion}
        isNarrow={isNarrow}
        onClose={closeInspector}
      />
    </div>
  );
}
