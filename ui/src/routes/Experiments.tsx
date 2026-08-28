import type { CSSProperties } from "react";
import { DEMO_EXPERIMENTS } from "../data/demoFixture";

const STATUS_LABEL: Record<string, string> = {
  baseline: "Official baseline",
  running: "Running",
  rejected: "Rejected",
  accepted: "Accepted — current best",
};

const STATUS_COLOR: Record<string, string> = {
  baseline: "var(--text-1)",
  running: "var(--status-success)",
  rejected: "var(--status-attention)",
  accepted: "var(--status-success)",
};

export function Experiments() {
  const baseline = DEMO_EXPERIMENTS.find((e) => e.status === "baseline")!;

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "var(--space-6)", maxWidth: 960 }}>
      <h1 style={{ fontSize: 18, marginBottom: "var(--space-1)" }}>Experiments</h1>
      <p style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 0 }}>
        Every run compared against the official FM baseline ({baseline.primary.toFixed(4)} primary), not an
        intermediate best.
      </p>

      <div style={cardStyle}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--text-2)" }}>
              <th scope="col" style={th}>
                Run
              </th>
              <th scope="col" style={th}>
                GAUC
              </th>
              <th scope="col" style={th}>
                nDCG@5
              </th>
              <th scope="col" style={th}>
                Primary
              </th>
              <th scope="col" style={th}>
                Δ vs. baseline
              </th>
              <th scope="col" style={th}>
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {DEMO_EXPERIMENTS.map((e) => {
              const delta = e.primary !== null ? e.primary - baseline.primary : null;
              return (
                <tr key={e.id}>
                  <td style={td}>{e.label}</td>
                  <td className="mono tabular" style={td}>
                    {e.gauc?.toFixed(4) ?? "—"}
                  </td>
                  <td className="mono tabular" style={td}>
                    {e.ndcg5?.toFixed(4) ?? "—"}
                  </td>
                  <td className="mono tabular" style={td}>
                    {e.primary?.toFixed(4) ?? "—"}
                  </td>
                  <td
                    className="mono tabular"
                    style={{ ...td, color: delta === null ? "var(--text-2)" : delta > 0 ? "var(--status-success)" : "var(--text-1)" }}
                  >
                    {delta === null ? "—" : `${delta > 0 ? "+" : ""}${delta.toFixed(4)}`}
                  </td>
                  <td style={{ ...td, color: STATUS_COLOR[e.status] }}>{STATUS_LABEL[e.status]}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p style={{ fontSize: 11.5, color: "var(--text-2)", marginTop: "var(--space-4)" }}>
        Convergence rule: stop when validation fails to improve by more than ε = 0.002 for N = 3 consecutive
        iterations. Small movements within seed noise (σ = 0.0008) are treated as unconfirmed.
      </p>
    </div>
  );
}

const cardStyle: CSSProperties = {
  marginTop: "var(--space-5)",
  background: "var(--surface-1)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-lg)",
  boxShadow: "var(--shadow-card)",
  padding: "var(--space-2) var(--space-5)",
};
const th: CSSProperties = { padding: "var(--space-3) var(--space-4) var(--space-3) 0", borderBottom: "1px solid var(--border)" };
const td: CSSProperties = { padding: "var(--space-3) var(--space-4) var(--space-3) 0", borderBottom: "1px solid var(--surface-2)" };
