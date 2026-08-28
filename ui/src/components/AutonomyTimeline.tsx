import type { CSSProperties } from "react";
import { DEMO_TIMELINE } from "../data/demoFixture";
import { NODES } from "../data/nodeRegistry";

export function AutonomyTimeline() {
  return (
    <div
      style={{
        background: "var(--surface-1)",
        boxShadow: "0 -1px 0 var(--border), 0 -2px 12px rgba(20, 22, 40, 0.05)",
        height: 148,
        display: "flex",
        flexDirection: "column",
        position: "relative",
        zIndex: 5,
      }}
      aria-label="Autonomy timeline"
    >
      <div
        style={{
          padding: "var(--space-2) var(--space-4)",
          fontSize: 11,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          color: "var(--text-2)",
          borderBottom: "1px solid var(--ink-3)",
        }}
      >
        Autonomy timeline
      </div>
      <div style={{ overflowX: "auto", flex: 1 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <caption className="visually-hidden">
            Chronological log of every stage action and outcome in this run
          </caption>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--text-2)" }}>
              <th scope="col" style={cellStyle}>
                Time
              </th>
              <th scope="col" style={cellStyle}>
                Stage
              </th>
              <th scope="col" style={cellStyle}>
                Action
              </th>
              <th scope="col" style={cellStyle}>
                Outcome
              </th>
              <th scope="col" style={cellStyle}>
                Duration
              </th>
            </tr>
          </thead>
          <tbody>
            {DEMO_TIMELINE.map((row, i) => {
              const def = NODES.find((n) => n.id === row.component);
              return (
                <tr key={i}>
                  <td className="mono tabular" style={cellStyle}>
                    {row.t}
                  </td>
                  <td style={cellStyle}>{def?.label ?? row.component}</td>
                  <td style={cellStyle}>{row.action}</td>
                  <td style={{ ...cellStyle, color: "var(--text-1)" }}>{row.outcome}</td>
                  <td className="mono tabular" style={cellStyle}>
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

const cellStyle: CSSProperties = {
  padding: "var(--space-2) var(--space-4)",
  borderBottom: "1px solid var(--ink-2)",
  whiteSpace: "nowrap",
};
