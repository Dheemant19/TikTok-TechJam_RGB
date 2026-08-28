import { GROUP_LABELS, GROUP_ORDER, NODES } from "../data/nodeRegistry";
import { laneColorFor } from "../liveworkflow/laneData";
import { statusMeta } from "../liveworkflow/NodeCard";
import { useRunStore } from "../liveworkflow/runStore";
import { useFlipInspector } from "../liveworkflow/useFlipInspector";
import { InspectorPanel } from "../liveworkflow/InspectorPanel";

// Accessible fallback for reduced motion and narrow screens: the same data as
// the 2D canvas, as a keyboard- and screen-reader-navigable list. The
// inspector still opens (as a bottom sheet), just without a card to morph from.
export function StageListFallback({ reducedMotion }: { reducedMotion: boolean }) {
  const nodeStatus = useRunStore((s) => s.nodeStatus);
  const { selectedId, overlayRect, overlayOpen, openNode, closeInspector } = useFlipInspector(reducedMotion);

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
                      openNode(n.id, { left: 0, top: window.innerHeight, width: window.innerWidth, height: 0 })
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

      <InspectorPanel
        nodeId={selectedId}
        status={selectedId ? nodeStatus[selectedId] : "waiting"}
        overlayRect={overlayRect}
        overlayOpen={overlayOpen}
        reducedMotion={reducedMotion}
        isNarrow
        onClose={closeInspector}
      />
    </div>
  );
}
