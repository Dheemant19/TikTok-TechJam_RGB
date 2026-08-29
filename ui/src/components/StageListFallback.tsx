import { useMemo } from "react";
import { GROUP_LABELS, GROUP_ORDER, NODES } from "../data/nodeRegistry";
import { computeInitialPositions, laneColorFor } from "../liveworkflow/laneData";
import { statusMeta } from "../liveworkflow/NodeCard";
import { useRunStore } from "../liveworkflow/runStore";
import { useFlipInspector } from "../liveworkflow/useFlipInspector";
import { StageFocusView } from "../liveworkflow/StageFocusView";

// Accessible fallback for reduced motion and narrow screens: the same data as
// the 2D canvas, as a keyboard- and screen-reader-navigable list. Stage focus
// opens from a synthetic lower-edge origin and uses the same stacked layout.
export function StageListFallback({ reducedMotion }: { reducedMotion: boolean }) {
  const nodeStatus = useRunStore((s) => s.nodeStatus);
  const nodeElapsed = useRunStore((s) => s.nodeElapsed);
  const positions = useMemo(() => computeInitialPositions(), []);
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

  return (
    <div style={{ overflowY: "auto", padding: "var(--space-4)", flex: 1 }}>
      {GROUP_ORDER.map((group) => (
        <section key={group} style={{ marginBottom: "var(--space-5)" }}>
          <h2
            style={{
              fontSize: 11,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              color: "var(--text-2)",
              margin: "0 0 var(--space-2)",
            }}
          >
            {GROUP_LABELS[group]}
          </h2>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: "var(--space-2)" }}>
            {NODES.filter((n) => n.group === group).map((n) => {
              const status = nodeStatus[n.id];
              const st = statusMeta(status, n.isRecovery);
              const colors = laneColorFor(n);
              const isSelected = selectedId === n.id;
              return (
                <li key={n.id}>
                  <button
                    onClick={() =>
                      openNode(n.id, { left: 0, top: Math.max(0, window.innerHeight - 1), width: window.innerWidth, height: 1 })
                    }
                    aria-pressed={isSelected}
                    style={{
                      width: "100%",
                      display: "flex",
                      alignItems: "center",
                      gap: "var(--space-3)",
                      textAlign: "left",
                      background: isSelected ? "var(--surface-2)" : "var(--surface-1)",
                      border: `1px solid ${isSelected ? "var(--primary)" : "var(--border)"}`,
                      borderRadius: "var(--radius-md)",
                      padding: "var(--space-3) var(--space-4)",
                      color: "var(--text-0)",
                      cursor: "pointer",
                    }}
                  >
                    <span
                      aria-hidden
                      style={{
                        width: 22,
                        height: 22,
                        borderRadius: 6,
                        flexShrink: 0,
                        background: `linear-gradient(135deg, ${colors.a}, ${colors.b})`,
                      }}
                    />
                    <span style={{ flex: 1, fontSize: 13 }}>{n.label}</span>
                    <span style={{ fontSize: 11.5, fontWeight: 700, color: st.color }}>{st.text}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}

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
        isNarrow
        onClose={closeInspector}
        onNavigate={navigateNode}
      />
    </div>
  );
}
