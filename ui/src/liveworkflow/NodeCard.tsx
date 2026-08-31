import type {
  CSSProperties,
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
} from "react";
import { GROUP_LABELS, NodeDef, NodeStatus } from "../data/nodeRegistry";
import { laneColorFor, laneIndex, shapeStyle, NODE_W, NODE_H, Vec2 } from "./laneData";

interface StatusMeta {
  text: string;
  color: string;
  dot: string;
}

const STATUS_MAP: Record<string, StatusMeta> = {
  waiting: { text: "Waiting", color: "var(--status-waiting)", dot: "var(--status-waiting-dot)" },
  ready: { text: "Ready", color: "var(--status-running)", dot: "var(--status-running-dot)" },
  running: { text: "Running", color: "var(--status-running)", dot: "var(--status-running-dot)" },
  succeeded: { text: "Succeeded", color: "var(--status-success)", dot: "var(--status-success-dot)" },
  failed: { text: "Failed", color: "var(--status-failed)", dot: "var(--status-failed-dot)" },
  rejected: { text: "Rejected", color: "var(--status-attention)", dot: "var(--status-attention-dot)" },
  paused: { text: "Paused", color: "var(--status-attention)", dot: "var(--status-attention-dot)" },
  skipped: { text: "Skipped", color: "var(--status-waiting)", dot: "var(--status-waiting-dot)" },
  blocked: { text: "Blocked", color: "var(--status-failed)", dot: "var(--status-failed-dot)" },
};

export function statusMeta(status: NodeStatus, isRecovery?: boolean): StatusMeta {
  const st = STATUS_MAP[status] ?? STATUS_MAP.waiting;
  if (isRecovery && status === "waiting") return { ...st, text: "Standby" };
  return st;
}

interface Props {
  node: NodeDef;
  position: Vec2;
  status: NodeStatus;
  elapsedMs: number;
  reducedMotion: boolean;
  isDragging: boolean;
  isSelected: boolean;
  isArriving?: boolean;
  mode?: "canvas" | "focus" | "context";
  interactive?: boolean;
  size?: { width: number; minHeight: number };
  onPointerDownCard?: (e: ReactPointerEvent<HTMLButtonElement>) => void;
  onOpen: (rect: DOMRect) => void;
}

type NodeStyle = CSSProperties & {
  "--node-a": string;
  "--node-b": string;
  "--node-shadow": string;
  "--rest-tilt": string;
};

export const FOCUS_NODE_W = 340;
export const FOCUS_NODE_H = 204;

// A small, deterministic per-card lean, fixed to the node id so it never
// shifts on re-render. It reads as a set of hand-placed index cards rather
// than a machine-perfect grid. Kept well under a degree; hover motion dominates.
function restTiltFor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) | 0;
  const deg = ((hash % 100) / 100 - 0.5) * 0.7;
  return `${deg.toFixed(2)}deg`;
}

export function NodeCard({
  node,
  position,
  status,
  elapsedMs,
  reducedMotion,
  isDragging,
  isSelected,
  mode = "canvas",
  isArriving = false,
  interactive = true,
  size,
  onPointerDownCard,
  onOpen,
}: Props) {
  const colors = laneColorFor(node);
  const isRunning = status === "running";
  const st = statusMeta(status, node.isRecovery);
  const laneLabel = GROUP_LABELS[node.group];

  const cardStyle: NodeStyle = {
    position: "absolute",
    left: position.x,
    top: position.y,
    width: size?.width ?? (mode === "focus" ? FOCUS_NODE_W : NODE_W),
    minHeight: size?.minHeight ?? (mode === "focus" ? FOCUS_NODE_H : NODE_H),
    "--node-a": colors.a,
    "--node-b": colors.b,
    "--node-shadow": colors.shadow,
    "--rest-tilt": restTiltFor(node.id),
    opacity: mode === "canvas" && isSelected ? 0 : status === "waiting" && node.isRecovery ? 0.76 : 1,
    // The overlay opens on `opacity 240ms var(--ease-focus)` (see
    // `.stage-focus-shell` in experience.css -- that custom property is
    // scoped to `.stage-focus-root`, a tree this canvas card never lives
    // inside, so the curve is inlined here rather than referenced). Fading
    // the source card out on the same duration keeps the hand-off from
    // card to overlay continuous instead of an instant pop before the
    // overlay has visually appeared (AGENTS.md #3, gap 1). Reduced motion
    // collapses this to an immediate swap, mirroring the reducedMotion
    // branch in useFlipInspector's openNode.
    transition: mode === "canvas" && isSelected
      ? `opacity ${reducedMotion ? 0 : 240}ms cubic-bezier(0.2, 0.8, 0.2, 1)`
      : undefined,
    pointerEvents: mode === "canvas" && isSelected ? "none" : undefined,
  };

  const badgeStyle: CSSProperties = {
    ...shapeStyle(node.group, node.isRecovery),
  };

  const monogramStyle: CSSProperties = {
    transform: laneIndex(node.group) === 2 && !node.isRecovery ? "rotate(-45deg)" : "none",
  };

  const resetTilt = (element: HTMLButtonElement) => {
    element.style.setProperty("--tilt-x", "0deg");
    element.style.setProperty("--tilt-y", "0deg");
    element.style.setProperty("--sheen-x", "50%");
    element.style.setProperty("--sheen-y", "50%");
  };

  return (
    <button
      type="button"
      aria-label={`${laneLabel}: ${node.label}, ${st.text}. Open stage evidence.`}
      data-node-id={node.id}
      aria-hidden={!interactive || (mode === "context" && isSelected) ? true : undefined}
      tabIndex={!interactive || (mode === "context" && isSelected) ? -1 : undefined}
      className={`workflow-node workflow-node--${mode} ${isRunning ? "is-running" : ""} ${isArriving && !reducedMotion ? "is-arriving" : ""} ${node.isRecovery ? "is-recovery" : ""} ${isDragging ? "is-dragging" : ""}`}
      style={cardStyle}
      onPointerDown={onPointerDownCard}
      onClick={(e: ReactMouseEvent<HTMLButtonElement>) => {
        if (interactive) onOpen(e.currentTarget.getBoundingClientRect());
      }}
      onPointerMove={(event) => {
        if (mode === "context" || reducedMotion || event.pointerType !== "mouse" || event.buttons) return;
        const rect = event.currentTarget.getBoundingClientRect();
        const px = (event.clientX - rect.left) / rect.width;
        const py = (event.clientY - rect.top) / rect.height;
        event.currentTarget.style.setProperty("--tilt-x", `${(0.5 - py) * 13}deg`);
        event.currentTarget.style.setProperty("--tilt-y", `${(px - 0.5) * 15}deg`);
        event.currentTarget.style.setProperty("--sheen-x", `${px * 100}%`);
        event.currentTarget.style.setProperty("--sheen-y", `${py * 100}%`);
      }}
      onPointerLeave={(event) => resetTilt(event.currentTarget)}
      onBlur={(event) => resetTilt(event.currentTarget)}
    >
      <span className="workflow-node__edge" aria-hidden="true" />
      <span className="workflow-node__sheen" aria-hidden="true" />
      <span className="workflow-node__badge" style={badgeStyle} aria-hidden="true">
        <span style={monogramStyle}>{node.mono}</span>
      </span>

      <span className="workflow-node__body">
        <span className="workflow-node__title">{node.label}</span>
        <span className="workflow-node__role">{node.archLabel}</span>

        <span className="workflow-node__footer">
          <span className="workflow-node__status" style={{ color: st.color }}>
            <span
              className={`workflow-node__status-dot ${isRunning ? "is-live" : ""}`}
              style={{ background: st.dot }}
              aria-hidden="true"
            />
            {st.text}
          </span>
          {isRunning ? (
            <span className="workflow-node__elapsed mono tabular">{(elapsedMs / 1000).toFixed(1)}s</span>
          ) : (
            <span className="workflow-node__inspect" aria-hidden="true">
              Inspect
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                <path d="M3 8h9M9 4.5 12.5 8 9 11.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
          )}
        </span>
      </span>
    </button>
  );
}
