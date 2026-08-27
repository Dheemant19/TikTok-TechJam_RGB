import { useMemo, useState } from "react";
import { CheckCircle2, CircleDashed, CircleMinus, ShieldAlert, XCircle } from "lucide-react";
import type { FrontierState, RunEvent, SessionSnapshot } from "@/api/types";
import styles from "./Routes.module.css";

interface ExperimentsProps {
  events: RunEvent[];
  snapshot: SessionSnapshot | null;
}

interface Metrics {
  GAUC: number;
  "nDCG@5": number;
  primary: number;
}

interface ExperimentContractPayload {
  experiment_id: string;
  hypothesis: string;
  primary_change: string;
  parent_run_id: string;
  comparator_run_id: string;
  minimum_primary_improvement: number;
  guardrails: string[];
}

interface ExperimentRow {
  runId: string;
  experimentId: string | null;
  hypothesis: string | null;
  primaryChange: string | null;
  parentRunId: string | null;
  metrics: Metrics | null;
  decision: string | null;
  recoveryAction: string | null;
  recoveryCategory: string | null;
  occurredAt: string;
}

interface BaselineSeedRun {
  seed: number;
  metrics: Metrics;
}

interface BaselineResult {
  reference_primary: number;
  observed_mean_primary: number;
  absolute_difference: number;
  tolerance: number;
  seeds: BaselineSeedRun[];
  status: string;
}

// RunEvent.payload is Record<string, unknown>; each event_type has a stable
// shape controlled by _event() in graph.py, so a keyed field read (not a
// full-object cast) is enough — no schema validator exists for it yet.
function payloadField<T>(payload: Record<string, unknown>, key: string): T | null {
  return key in payload ? (payload[key] as T) : null;
}

function frontierBadge(frontier: FrontierState | null, runId: string): { label: string; icon: typeof CheckCircle2; tone: string } | null {
  if (!frontier) return null;
  if (frontier.validation_best === runId) return { label: "Current best", icon: CheckCircle2, tone: "success" };
  if (frontier.stable_fallback === runId) return { label: "Stable fallback", icon: ShieldAlert, tone: "info" };
  if (frontier.pending_candidate === runId) return { label: "Pending", icon: CircleDashed, tone: "neutral" };
  if (frontier.failed.includes(runId)) return { label: "Failed", icon: XCircle, tone: "danger" };
  if (frontier.rejected.includes(runId)) return { label: "Rejected", icon: CircleMinus, tone: "neutral" };
  return null;
}

export function Experiments({ events, snapshot }: ExperimentsProps) {
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);

  const baseline = useMemo(() => {
    const event = [...events].reverse().find((item) => item.component_id === "ledger" && item.stage === "baseline" && item.event_type === "frontier");
    return event ? payloadField<BaselineResult>(event.payload, "baseline_result") : null;
  }, [events]);

  const rows = useMemo<ExperimentRow[]>(() => {
    const byRun = new Map<string, ExperimentRow>();
    for (const event of events) {
      if (event.run_id === "workflow") continue;
      const existing = byRun.get(event.run_id) ?? {
        runId: event.run_id, experimentId: null, hypothesis: null, primaryChange: null, parentRunId: null,
        metrics: null, decision: null, recoveryAction: null, recoveryCategory: null, occurredAt: event.occurred_at,
      };
      if (event.component_id === "scientist" && event.event_type === "plan") {
        const contract = payloadField<ExperimentContractPayload>(event.payload, "contract");
        if (contract) {
          existing.experimentId = contract.experiment_id;
          existing.hypothesis = contract.hypothesis;
          existing.primaryChange = contract.primary_change;
          existing.parentRunId = contract.parent_run_id;
        }
      }
      if (event.component_id === "evaluator" && event.event_type === "metric") {
        existing.metrics = payloadField<Metrics>(event.payload, "metrics");
      }
      if (event.component_id === "watchdog" && event.event_type === "frontier") {
        existing.decision = payloadField<string>(event.payload, "decision");
      }
      if (event.component_id === "recovery") {
        existing.recoveryAction = payloadField<string>(event.payload, "action");
        existing.recoveryCategory = payloadField<string>(event.payload, "category");
      }
      byRun.set(event.run_id, existing);
    }
    return [...byRun.values()].sort((a, b) => a.occurredAt.localeCompare(b.occurredAt));
  }, [events]);

  const frontier = snapshot?.frontier ?? null;

  return (
    <div className={styles.page}>
      <h1>Experiments</h1>
      <p className="text-small">Every candidate is compared against its parent run and the official FM baseline. No result is final until convergence or budget exhaustion.</p>

      {baseline && (
        <section className={styles.card}>
          <h2>Official FM baseline (B0)</h2>
          <p className="text-small">
            Reference primary score {baseline.reference_primary.toFixed(4)}; reproduced {baseline.observed_mean_primary.toFixed(4)} (Δ{" "}
            {baseline.absolute_difference.toFixed(5)}, tolerance {baseline.tolerance}).
          </p>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Seed</th>
                <th>GAUC</th>
                <th>nDCG@5</th>
                <th>Primary</th>
              </tr>
            </thead>
            <tbody>
              {baseline.seeds.map((run) => (
                <tr key={run.seed}>
                  <td>{run.seed}</td>
                  <td>{run.metrics.GAUC.toFixed(4)}</td>
                  <td>{run.metrics["nDCG@5"].toFixed(4)}</td>
                  <td>{run.metrics.primary.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className={styles.card}>
        <h2>Candidate experiments</h2>
        {rows.length === 0 ? (
          <p className="text-small">No experiments have run yet in this session.</p>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Run</th>
                <th>Status</th>
                <th>GAUC</th>
                <th>nDCG@5</th>
                <th>Primary</th>
                <th>Δ vs. FM baseline</th>
                <th>Decision</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const badge = frontierBadge(frontier, row.runId);
                const deltaVsBaseline = row.metrics && baseline ? row.metrics.primary - baseline.reference_primary : null;
                return (
                  <>
                    <tr
                      key={row.runId}
                      className={styles.clickableRow}
                      tabIndex={0}
                      role="button"
                      onClick={() => setExpandedRunId(expandedRunId === row.runId ? null : row.runId)}
                      onKeyDown={(event) => event.key === "Enter" && setExpandedRunId(expandedRunId === row.runId ? null : row.runId)}
                    >
                      <td>{row.runId}</td>
                      <td>{badge ? <span className={`${styles.badge} ${styles[`badge-${badge.tone}`]}`}>{badge.label}</span> : "In progress"}</td>
                      <td>{row.metrics?.GAUC.toFixed(4) ?? "—"}</td>
                      <td>{row.metrics?.["nDCG@5"].toFixed(4) ?? "—"}</td>
                      <td>{row.metrics?.primary.toFixed(4) ?? "—"}</td>
                      <td>{deltaVsBaseline === null ? "—" : `${deltaVsBaseline >= 0 ? "+" : ""}${deltaVsBaseline.toFixed(4)}`}</td>
                      <td>{row.decision ?? (row.recoveryAction ? "recovering" : "pending")}</td>
                    </tr>
                    {expandedRunId === row.runId && (
                      <tr>
                        <td colSpan={7}>
                          <div className={styles.detailPanel}>
                            <p><strong>Hypothesis:</strong> {row.hypothesis ?? "—"}</p>
                            <p><strong>Change:</strong> {row.primaryChange ?? "—"}</p>
                            <p><strong>Parent run:</strong> {row.parentRunId ?? "—"}</p>
                            {row.recoveryAction && (
                              <p><strong>Recovery:</strong> {row.recoveryCategory} — {row.recoveryAction}</p>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
