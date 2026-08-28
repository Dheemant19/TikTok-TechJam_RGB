import type { CSSProperties } from "react";
import { DEMO_TIMELINE } from "../data/demoFixture";
import { NODES } from "../data/nodeRegistry";

export function AutonomyLog() {
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "var(--space-6)", maxWidth: 1200, width: "100%", margin: "0 auto" }}>
      <h1 style={{ fontSize: 18, marginBottom: "var(--space-1)" }}>Autonomy Log</h1>
      <p style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 0 }}>
        Chronological record of every stage action and outcome — the same evidence the Live Workflow view surfaces in
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
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <caption className="visually-hidden">Chronological log of every stage action and outcome in this run</caption>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--text-2)" }}>
              <th scope="col" style={th}>
                Time
              </th>
              <th scope="col" style={th}>
                Stage
              </th>
              <th scope="col" style={th}>
                Action
              </th>
              <th scope="col" style={th}>
                Outcome
              </th>
              <th scope="col" style={th}>
                Duration
              </th>
            </tr>
          </thead>
          <tbody>
            {DEMO_TIMELINE.map((row, i) => {
              const def = NODES.find((n) => n.id === row.component);
              return (
                <tr key={i}>
                  <td className="mono tabular" style={td}>
                    {row.t}
                  </td>
                  <td style={td}>{def?.label ?? row.component}</td>
                  <td style={td}>{row.action}</td>
                  <td style={{ ...td, color: "var(--text-1)" }}>{row.outcome}</td>
                  <td className="mono tabular" style={td}>
                    {row.duration}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const th: CSSProperties = { padding: "var(--space-3) var(--space-5)", borderBottom: "1px solid var(--border)" };
const td: CSSProperties = { padding: "var(--space-3) var(--space-5)", borderBottom: "1px solid var(--surface-2)" };
