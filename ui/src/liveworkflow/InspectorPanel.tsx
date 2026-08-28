import { useEffect, useState, type CSSProperties } from "react";
import { NODES, NodeStatus } from "../data/nodeRegistry";
import { laneColorFor, NODE_DETAILS } from "./laneData";
import { statusMeta } from "./NodeCard";

type Tab = "summary" | "input" | "output" | "history";

export interface OverlayRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

interface Props {
  nodeId: string | null;
  status: NodeStatus;
  overlayRect: OverlayRect | null;
  overlayOpen: boolean;
  reducedMotion: boolean;
  isNarrow: boolean;
  onClose: () => void;
}

const EASING = "cubic-bezier(.2,.8,.2,1)";

export function InspectorPanel({ nodeId, status, overlayRect, overlayOpen, reducedMotion, isNarrow, onClose }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("summary");

  useEffect(() => {
    if (nodeId) setActiveTab("summary");
  }, [nodeId]);

  useEffect(() => {
    if (!nodeId) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [nodeId, onClose]);

  if (!nodeId) return null;
  const node = NODES.find((n) => n.id === nodeId);
  if (!node) return null;
  const detail = NODE_DETAILS[nodeId];
  const colors = laneColorFor(node);
  const st = statusMeta(status, node.isRecovery);

  const targetW = isNarrow ? window.innerWidth : Math.min(760, window.innerWidth - 80);
  const targetH = isNarrow ? Math.round(window.innerHeight * 0.86) : window.innerHeight - 96;
  const targetL = isNarrow ? 0 : (window.innerWidth - targetW) / 2;
  const targetT = isNarrow ? window.innerHeight - targetH : 48;

  const open = reducedMotion ? true : overlayOpen;
  const panelStyle: CSSProperties = overlayRect
    ? {
        position: "fixed",
        left: open ? targetL : overlayRect.left,
        top: open ? targetT : overlayRect.top,
        width: open ? targetW : overlayRect.width,
        height: open ? targetH : overlayRect.height,
        borderRadius: open ? (isNarrow ? 20 : 26) : 18,
        background: "#fff",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        zIndex: 1000,
        boxShadow: open ? "0 50px 110px -24px rgba(15,23,42,.5)" : "0 10px 30px -10px rgba(15,23,42,.3)",
        transition: reducedMotion
          ? "none"
          : `left .5s ${EASING}, top .5s ${EASING}, width .5s ${EASING}, height .5s ${EASING}, border-radius .5s ${EASING}, box-shadow .5s ease`,
      }
    : { display: "none" };

  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(15,23,42,.35)",
          opacity: open ? 1 : 0,
          transition: reducedMotion ? "none" : "opacity .4s ease",
          zIndex: 999,
        }}
      />
      <div style={panelStyle} role="dialog" aria-modal="true" aria-label={node.label}>
        <div style={{ position: "relative", padding: "24px 24px 20px 24px", background: `linear-gradient(135deg, ${colors.a}, ${colors.b})`, flexShrink: 0 }}>
          <button
            onClick={onClose}
            aria-label="Close inspector"
            style={{
              position: "absolute",
              top: 16,
              right: 16,
              width: 32,
              height: 32,
              borderRadius: 10,
              border: "none",
              background: "rgba(255,255,255,.25)",
              color: "#fff",
              fontSize: 15,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            ✕
          </button>
          <div
            style={{
              width: 56,
              height: 56,
              background: "rgba(255,255,255,.22)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: 14,
              border: "1px solid rgba(255,255,255,.35)",
            }}
          >
            <span style={{ color: "#fff", fontWeight: 800, fontSize: 16 }}>{node.mono}</span>
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: "#fff", letterSpacing: "-.01em", marginTop: 14 }}>{node.label}</div>
          <div style={{ fontSize: 12.5, color: "rgba(255,255,255,.85)", fontWeight: 600, marginTop: 2 }}>{node.archLabel}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 12 }}>
            <span aria-hidden style={{ width: 7, height: 7, borderRadius: "50%", background: "rgba(255,255,255,.7)" }} />
            <span style={{ fontSize: 12.5, fontWeight: 700, color: "#fff" }}>{st.text}</span>
          </div>
        </div>

        <div style={{ display: "flex", gap: 4, padding: "14px 24px 0 24px", borderBottom: "1px solid rgba(15,23,42,.08)", flexShrink: 0 }} role="tablist">
          {(["summary", "input", "output", "history"] as Tab[]).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={activeTab === t}
              onClick={() => setActiveTab(t)}
              style={{
                padding: "10px 14px",
                border: "none",
                background: "none",
                cursor: "pointer",
                fontSize: 13,
                fontWeight: 700,
                textTransform: "capitalize",
                color: activeTab === t ? "#0f172a" : "#94a3b8",
                borderBottom: activeTab === t ? "2px solid #3b82f6" : "2px solid transparent",
              }}
            >
              {t}
            </button>
          ))}
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "22px 24px 32px 24px" }}>
          {activeTab === "summary" && (
            <>
              <div style={{ fontSize: 14.5, lineHeight: 1.65, color: "#334155" }}>{detail.summary}</div>
              <div style={{ marginTop: 20, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                {detail.facts.map((f) => (
                  <div key={f.label} style={{ background: "#f8fafc", border: "1px solid rgba(15,23,42,.06)", borderRadius: 12, padding: "12px 14px" }}>
                    <div style={{ fontSize: 10.5, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: ".04em" }}>{f.label}</div>
                    <div style={{ fontSize: 13.5, fontWeight: 700, color: "#0f172a", marginTop: 4 }}>{f.value}</div>
                  </div>
                ))}
              </div>
            </>
          )}
          {(activeTab === "input" || activeTab === "output") &&
            (activeTab === "input" ? detail.input : detail.output).map((row) => (
              <div key={row.label} style={{ padding: "12px 0", borderBottom: "1px solid rgba(15,23,42,.06)" }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8" }}>{row.label}</div>
                <div
                  style={{
                    fontSize: 13.5,
                    color: "#1e293b",
                    marginTop: 4,
                    fontFamily: row.mono ? "var(--font-mono)" : "inherit",
                    lineHeight: 1.5,
                  }}
                >
                  {row.value}
                </div>
              </div>
            ))}
          {activeTab === "history" &&
            detail.history.map((h) => (
              <div key={h.attempt + h.status} style={{ display: "flex", gap: 12, padding: "12px 0", borderBottom: "1px solid rgba(15,23,42,.06)" }}>
                <div style={{ width: 6, height: 6, borderRadius: "50%", background: h.dotColor, marginTop: 6, flexShrink: 0 }} />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>
                    Attempt {h.attempt} — {h.status}
                  </div>
                  <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 2 }}>
                    {h.time} · {h.note}
                  </div>
                </div>
              </div>
            ))}
        </div>
      </div>
    </>
  );
}
