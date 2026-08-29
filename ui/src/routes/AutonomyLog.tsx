import { useMemo, type CSSProperties } from "react";
import { selectAutonomyTimeline } from "../liveworkflow/selectors";
import { useRunStore } from "../liveworkflow/runStore";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function AutonomyLog() {
  const events = useRunStore((state) => state.events);
  const rows = useMemo(() => selectAutonomyTimeline(events), [events]);

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "var(--space-6)", maxWidth: 1200, width: "100%", margin: "0 auto" }}>
      <h1 style={{ fontFamily: "var(--font-display)", fontSize: 32, fontWeight: 560, letterSpacing: "-0.012em", marginBottom: "var(--space-2)" }}>Autonomy Log</h1>
      <p style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 0 }}>
        Chronological record of every stage action and outcome. This is the same evidence the Live Workflow view surfaces in
        real time.
      </p>

      <div
        style={{
          marginTop: "var(--space-5)",
          background: "var(--surface-1)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-lg)",
          boxShadow: "var(--shadow-card)",
          overflow: "hidden",
        }}
      >
        {rows.length === 0 ? (
          <div style={{ padding: "var(--space-5)", textAlign: "center", color: "var(--text-2)", fontSize: 12.5 }}>
            No events recorded yet. Start a run from Live Workflow to populate this log.
          </div>
        ) : (
          <table className="data-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <caption className="visually-hidden">Chronological log of every stage action and outcome in this run</caption>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--text-2)" }}>
                <th scope="col" style={th}>Time</th>
                <th scope="col" style={th}>Sequence</th>
                <th scope="col" style={th}>Stage</th>
                <th scope="col" style={th}>Action</th>
                <th scope="col" style={th}>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.sequence}>
                  <td className="mono tabular" style={td}>{formatTime(row.occurredAt)}</td>
                  <td className="mono tabular" style={td}>{row.sequence}</td>
                  <td style={td}>{row.componentLabel}</td>
                  <td style={{ ...td, color: "var(--text-1)" }}>{row.action}</td>
                  <td className="mono" style={td}>{row.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

const th: CSSProperties = { padding: "var(--space-3) var(--space-5)", borderBottom: "1px solid var(--border)" };
const td: CSSProperties = { padding: "var(--space-3) var(--space-5)", borderBottom: "1px solid var(--surface-2)" };
