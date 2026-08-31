import { useMemo, type CSSProperties } from "react";
import { RouteEmptyState } from "../components/RouteEmptyState";
import { selectResources } from "../liveworkflow/selectors";
import { useRunStore } from "../liveworkflow/runStore";

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

export function Resources() {
  const events = useRunStore((state) => state.events);
  const snapshot = useRunStore((state) => state.snapshot);
  const resources = useMemo(() => selectResources(events), [events]);
  const totalTokens = resources.bedrockInputTokens + resources.bedrockOutputTokens;
  const inputShare = totalTokens > 0 ? resources.bedrockInputTokens / totalTokens : 0;
  // The server counts interventions in its own append-only table; the snapshot
  // is authoritative even before the first resource receipt exists.
  const interventions = snapshot?.manual_interventions ?? resources.manualInterventions;
  const hasResourceEvidence =
    interventions > 0 || events.some((event) => event.component_id === "trainer" && event.event_type === "usage");

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "var(--space-6)", maxWidth: 1200, width: "100%", margin: "0 auto" }}>
      <h1 style={{ fontFamily: "var(--font-display)", fontSize: 32, fontWeight: 560, letterSpacing: "-0.012em", marginBottom: "var(--space-2)" }}>Resources</h1>
      <p style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 0 }}>
        Cumulative usage since the first agent action, tracked alongside the metric score, not as a footnote.
      </p>

      {!hasResourceEvidence ? (
        <RouteEmptyState
          icon="resources"
          title="No resource receipts yet"
          description="Usage appears after a run records real training or model activity. Token counts, wall time, memory, retries, and interventions will stay tied to that evidence."
        />
      ) : (
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
              <td style={rowLabel}>LLM tokens</td>
              <td style={rowValueCell}>
                <div className="mono tabular" style={{ marginBottom: "var(--space-2)" }}>
                  {resources.bedrockInputTokens.toLocaleString()} in / {resources.bedrockOutputTokens.toLocaleString()} out ({totalTokens.toLocaleString()} total)
                </div>
                <div style={{ height: 6, borderRadius: 999, background: "var(--surface-2)", overflow: "hidden", maxWidth: 320 }}>
                  <div style={{ height: "100%", width: `${inputShare * 100}%`, background: "var(--status-running-dot)" }} />
                </div>
              </td>
            </tr>
            <tr>
              <td style={rowLabel}>GPU / CPU wall time</td>
              <td style={{ ...rowValueCell }} className="mono tabular">{formatDuration(resources.wallSeconds)}</td>
            </tr>
            <tr>
              <td style={rowLabel}>GPU-hours</td>
              <td style={{ ...rowValueCell }} className="mono tabular">
                {resources.gpuHours === null ? "Not measured (no GPU compute observed)" : resources.gpuHours.toFixed(4)}
              </td>
            </tr>
            <tr>
              <td style={rowLabel}>Peak GPU memory</td>
              <td style={{ ...rowValueCell }} className="mono tabular">
                {resources.peakGpuMemoryMb === null
                  ? "Not measured (per-process GPU memory accounting unavailable)"
                  : `${resources.peakGpuMemoryMb.toFixed(0)} MB`}
              </td>
            </tr>
            <tr>
              <td style={rowLabel}>Peak RSS memory</td>
              <td style={{ ...rowValueCell }} className="mono tabular">{resources.peakRssMb.toFixed(0)} MB</td>
            </tr>
            <tr>
              <td style={rowLabel}>Recovery retries</td>
              <td style={{ ...rowValueCell }} className="mono tabular">{resources.retries}</td>
            </tr>
            <tr>
              <td style={rowLabel}>Manual interventions</td>
              <td style={{ ...rowValueCell }} className="mono tabular">{interventions}</td>
            </tr>
          </tbody>
        </table>
      )}
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
