import type { CSSProperties } from "react";
import { DEMO_RESOURCES } from "../data/demoFixture";

function formatDuration(seconds: number) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

export function Resources() {
  const r = DEMO_RESOURCES;
  const totalTokens = r.llmInputTokens + r.llmOutputTokens;
  const inputShare = r.llmInputTokens / totalTokens;

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "var(--space-6)", maxWidth: 1200, width: "100%", margin: "0 auto" }}>
      <h1 style={{ fontSize: 18, marginBottom: "var(--space-1)" }}>Resources</h1>
      <p style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 0 }}>
        Cumulative usage since the first agent action, tracked alongside the metric score, not as a footnote.
      </p>

      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: 13,
          marginTop: "var(--space-6)",
          background: "var(--surface-1)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-lg)",
          boxShadow: "var(--shadow-card)",
          overflow: "hidden",
        }}
      >
        <tbody>
          <tr>
            <th scope="row" style={rowLabel}>
              LLM tokens
            </th>
            <td style={rowValueCell}>
              <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
                <div style={{ flex: 1, background: "var(--ink-2)", borderRadius: "var(--radius-sm)", height: 8, overflow: "hidden", display: "flex" }}>
                  <div style={{ width: `${inputShare * 100}%`, background: "var(--status-success)" }} />
                  <div style={{ width: `${(1 - inputShare) * 100}%`, background: "var(--status-attention)" }} />
                </div>
                <span className="mono tabular" style={{ fontSize: 13, minWidth: 84, textAlign: "right" }}>
                  {totalTokens.toLocaleString()}
                </span>
              </div>
              <p style={{ fontSize: 11, color: "var(--text-2)", margin: "var(--space-1) 0 0" }}>
                {r.llmInputTokens.toLocaleString()} in · {r.llmOutputTokens.toLocaleString()} out
              </p>
            </td>
          </tr>
          <tr>
            <th scope="row" style={rowLabel}>
              GPU-hours
            </th>
            <td style={rowValueCell}>
              <span className="mono tabular" style={{ fontSize: 13 }}>
                {r.gpuHours.toFixed(1)}
              </span>
            </td>
          </tr>
          <tr>
            <th scope="row" style={rowLabel}>
              Wall-clock time
            </th>
            <td style={rowValueCell}>
              <span className="mono tabular" style={{ fontSize: 13 }}>
                {formatDuration(r.wallClockSeconds)}
              </span>
            </td>
          </tr>
          <tr>
            <th scope="row" style={rowLabel}>
              Manual interventions
            </th>
            <td style={rowValueCell}>
              <span
                className="mono tabular"
                style={{ fontSize: 13, color: r.manualInterventions === 0 ? "var(--status-success)" : "var(--status-attention)" }}
              >
                {r.manualInterventions}
              </span>
              <p style={{ fontSize: 11, color: "var(--text-2)", margin: "var(--space-1) 0 0" }}>
                {r.manualInterventions === 0
                  ? "Target met: zero required human intervention so far."
                  : "Each intervention is counted and explained in the ledger."}
              </p>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

const rowLabel: CSSProperties = {
  textAlign: "left",
  fontWeight: 500,
  fontSize: 12,
  color: "var(--text-1)",
  padding: "var(--space-4) var(--space-4) var(--space-4) var(--space-5)",
  borderBottom: "1px solid var(--surface-2)",
  width: 180,
  verticalAlign: "top",
};
const rowValueCell: CSSProperties = {
  padding: "var(--space-4) var(--space-5) var(--space-4) 0",
  borderBottom: "1px solid var(--surface-2)",
};
