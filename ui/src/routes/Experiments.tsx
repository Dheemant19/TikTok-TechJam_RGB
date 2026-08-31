import { useMemo, type CSSProperties } from "react";
import { RouteEmptyState } from "../components/RouteEmptyState";
import { selectExperiments } from "../liveworkflow/selectors";
import { useRunStore } from "../liveworkflow/runStore";

const STATUS_LABEL: Record<string, string> = {
  baseline: "Official baseline",
  running: "Running",
  rejected: "Rejected",
  ambiguous: "Ambiguous (within noise)",
  accepted: "Accepted, current best",
  failed: "Failed",
};

const STATUS_COLOR: Record<string, string> = {
  baseline: "var(--text-1)",
  running: "var(--status-running)",
  rejected: "var(--status-attention)",
  ambiguous: "var(--status-attention)",
  accepted: "var(--status-success)",
  failed: "var(--status-failed)",
};

function formatMetric(value: number | null): string {
  return value === null ? "-" : value.toFixed(4);
}

export function Experiments() {
  const events = useRunStore((state) => state.events);
  const rows = useMemo(() => selectExperiments(events), [events]);
  const baseline = rows.find((row) => row.status === "baseline");
  const attempts = rows.filter((row) => row.status !== "baseline");
  const evaluated = attempts.filter((row) => row.primary !== null);

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "var(--space-6)", maxWidth: 1200, width: "100%", margin: "0 auto" }}>
      <h1 style={{ fontFamily: "var(--font-display)", fontSize: 32, fontWeight: 560, letterSpacing: "-0.012em", marginBottom: "var(--space-2)" }}>Experiments</h1>
      <p style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 0 }}>
        {baseline
          ? `The official FM baseline (${formatMetric(baseline.primary)} primary) anchors reported improvement; promotion compares each candidate with the current validation best.`
          : "The official FM baseline has not been reproduced yet in this session."}
      </p>
      {attempts.length > 0 && (
        <p style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 0 }}>
          {attempts.length} bounded experiment attempt{attempts.length === 1 ? "" : "s"} recorded;{" "}
          {evaluated.length} reached full training and official validation and therefore consumed the completed-experiment
          limit. Failed research, code, and proxy attempts remain visible and consume their bounded recovery and resource
          budgets, but not completed-experiment slots.
        </p>
      )}

      {rows.length === 0 ? (
        <RouteEmptyState
          icon="experiments"
          title="No experiments recorded"
          description="Start a run to reproduce the official baseline, test bounded research ideas, and keep every accepted, rejected, or failed attempt visible."
        />
      ) : (
        <div style={cardStyle}>
          <table className="data-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
            <thead>
              <tr>
                <th style={th}>Experiment</th>
                <th style={th}>GAUC</th>
                <th style={th}>nDCG@5</th>
                <th style={th}>Primary</th>
                <th style={th}>Evidence Source</th>
                <th style={th}>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td style={td}>{row.label}</td>
                  <td style={td} className="tabular">{formatMetric(row.gauc)}</td>
                  <td style={td} className="tabular">{formatMetric(row.ndcg5)}</td>
                  <td style={td} className="tabular">{formatMetric(row.primary)}</td>
                  <td style={td}>{row.evidenceSource ?? "-"}</td>
                  <td style={{ ...td, color: STATUS_COLOR[row.status] }}>{STATUS_LABEL[row.status]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p style={{ fontSize: 11.5, color: "var(--text-2)", marginTop: "var(--space-4)" }}>
        Convergence rule: stop when validation fails to improve by more than epsilon = 0.002 for N = 3 consecutive
        iterations. Small movements within seed noise (sigma = 0.0008) are treated as unconfirmed.
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
const th: CSSProperties = { textAlign: "left", padding: "var(--space-3) var(--space-4) var(--space-3) 0", borderBottom: "1px solid var(--border)" };
const td: CSSProperties = { padding: "var(--space-3) var(--space-4) var(--space-3) 0", borderBottom: "1px solid var(--surface-2)" };
