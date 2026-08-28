import type { CSSProperties, MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from "react";
import { NodeDef, NodeStatus } from "../data/nodeRegistry";
import { laneColorFor, laneIndex, shapeStyle, NODE_W, NODE_H, Vec2 } from "./laneData";

interface StatusMeta {
  text: string;
  color: string;
  dot: string;
}

const STATUS_MAP: Record<string, StatusMeta> = {
  waiting: { text: "Waiting", color: "#94a3b8", dot: "#cbd5e1" },
  running: { text: "Running", color: "#2563eb", dot: "#3b82f6" },
  succeeded: { text: "Succeeded", color: "#16a34a", dot: "#22c55e" },
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
  onPointerDownCard: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onOpen: (rect: DOMRect) => void;
}

export function NodeCard({ node, position, status, elapsedMs, reducedMotion, onPointerDownCard, onOpen }: Props) {
  const colors = laneColorFor(node);
  const isRunning = status === "running";
  const st = statusMeta(status, node.isRecovery);

  const cardStyle: CSSProperties = {
    position: "absolute",
    left: position.x,
    top: position.y,
    width: NODE_W,
    minHeight: NODE_H,
    background: "#fff",
    borderRadius: 18,
    cursor: "pointer",
    touchAction: "none",
    border: node.isRecovery ? "2px dashed rgba(148,163,184,.6)" : "1px solid rgba(15,23,42,.06)",
    boxShadow: isRunning
      ? undefined
      : `0 10px 26px -12px rgba(15,23,42,.18), 0 0 0 2px ${colors.shadow}, 0 0 18px 1px ${colors.shadow}`,
    animation: isRunning && !reducedMotion ? "runGlow 1.4s ease-in-out infinite" : "none",
    transition: "box-shadow .25s ease, transform .3s cubic-bezier(.2,.8,.2,1)",
    opacity: status === "waiting" && node.isRecovery ? 0.75 : 1,
  };

  const badgeStyle: CSSProperties = {
    position: "absolute",
    top: -14,
    left: 16,
    width: 44,
    height: 44,
    background: `linear-gradient(135deg, ${colors.a}, ${colors.b})`,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    boxShadow: `0 8px 18px -4px ${colors.shadow}`,
    ...shapeStyle(node.group, node.isRecovery),
  };

  const monogramStyle: CSSProperties = {
    color: "#fff",
    fontWeight: 800,
    fontSize: 13,
    letterSpacing: "-.02em",
    transform: laneIndex(node.group) === 2 && !node.isRecovery ? "rotate(-45deg)" : "none",
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`${node.label}, ${st.text}`}
      style={cardStyle}
      onPointerDown={onPointerDownCard}
      onClick={(e: ReactMouseEvent<HTMLDivElement>) => onOpen(e.currentTarget.getBoundingClientRect())}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen(e.currentTarget.getBoundingClientRect());
        }
      }}
      onMouseEnter={(e) => {
        if (reducedMotion) return;
        e.currentTarget.style.transform = "perspective(900px) rotateX(-3deg) rotateY(3deg) translateY(-5px) scale(1.015)";
        e.currentTarget.style.boxShadow = `0 22px 44px -14px ${colors.shadow}`;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "none";
        e.currentTarget.style.boxShadow = cardStyle.boxShadow ?? "";
      }}
      onFocus={(e) => {
        e.currentTarget.style.outline = "2px solid #3b82f6";
        e.currentTarget.style.outlineOffset = "3px";
      }}
      onBlur={(e) => {
        e.currentTarget.style.outline = "none";
      }}
    >
      <div style={badgeStyle}>
        <span style={monogramStyle}>{node.mono}</span>
      </div>
      <div style={{ padding: "44px 16px 14px 16px" }}>
        <div style={{ fontSize: 14, fontWeight: 800, color: "#0f172a", letterSpacing: "-.01em" }}>{node.label}</div>
        <div style={{ fontSize: 11, color: "#94a3b8", fontWeight: 600, marginTop: 2 }}>{node.archLabel}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 14 }}>
          <span
            aria-hidden
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: st.dot,
              flexShrink: 0,
              animation: isRunning && !reducedMotion ? "pulseDot 1s ease-in-out infinite" : "none",
            }}
          />
          <span style={{ fontSize: 12, fontWeight: 700, color: st.color }}>{st.text}</span>
          {isRunning && (
            <span style={{ fontSize: 11, color: "#94a3b8", fontWeight: 600, fontFamily: "var(--font-mono)", marginLeft: "auto" }}>
              {(elapsedMs / 1000).toFixed(1)}s
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
