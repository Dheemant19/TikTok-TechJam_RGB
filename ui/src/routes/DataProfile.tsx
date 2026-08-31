import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { api } from "../api/client";
import { asArray, asRecord, field } from "../api/json";
import { RouteEmptyState } from "../components/RouteEmptyState";
import type { JsonRecord } from "../api/types";
import { useRunStore } from "../liveworkflow/runStore";

function numberOf(record: JsonRecord | undefined, key: string): number | null {
  const value = field(record, key);
  return typeof value === "number" ? value : null;
}
function stringOf(record: JsonRecord | undefined, key: string): string {
  const value = field(record, key);
  return typeof value === "string" ? value : "-";
}


export function DataProfile() {
  const events = useRunStore((state) => state.events);
  const [profile, setProfile] = useState<JsonRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  const latest = useMemo(() => {
    const completed = [...events].reverse().find((event) => event.component_id === "data_profiler" && event.event_type === "completed");
    if (!completed) return null;
    const payload = asRecord(completed.payload);
    const profileArtifact = asRecord(field(asRecord(field(payload, "profile")), "profile"));
    const receiptArtifact = asRecord(field(asRecord(field(payload, "transform")), "receipt"));
    return {
      profileArtifactId: typeof field(profileArtifact, "artifact_id") === "string" ? String(field(profileArtifact, "artifact_id")) : null,
      transformReceiptHash: typeof field(receiptArtifact, "content_hash") === "string" ? String(field(receiptArtifact, "content_hash")) : null,
    };
  }, [events]);

  useEffect(() => {
    if (!latest?.profileArtifactId) {
      setProfile(null);
      return;
    }
    let cancelled = false;
    api
      .getArtifact(latest.profileArtifactId)
      .then((response) => {
        if (!cancelled) setProfile(asRecord(response.content) ?? null);
      })
      .catch((requestError: unknown) => {
        if (!cancelled) setError(requestError instanceof Error ? requestError.message : String(requestError));
      });
    return () => {
      cancelled = true;
    };
  }, [latest?.profileArtifactId]);

  const splitStats = asArray(field(profile ?? undefined, "split_stats")) ?? [];
  const labelGroups = asArray(field(profile ?? undefined, "label_groups")) ?? [];
  const interactions = asArray(field(profile ?? undefined, "interactions_per_user")) ?? [];
  const missing = asRecord(field(profile ?? undefined, "missing_by_field"));
  const cardinalities = asRecord(field(profile ?? undefined, "cardinalities"));
  const censoring = asRecord(field(profile ?? undefined, "watch_time_censoring"));
  const duplicateRate = numberOf(profile ?? undefined, "duplicate_exposure_rate");

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "var(--space-6)", maxWidth: 1200, width: "100%", margin: "0 auto" }}>
      <h1 style={{ fontFamily: "var(--font-display)", fontSize: 32, fontWeight: 560, letterSpacing: "-0.012em", marginBottom: "var(--space-2)" }}>Data Profile</h1>
      <p style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 0 }}>
        Frozen train-only transform, computed once per run and reused while inputs are unchanged.
        {latest?.transformReceiptHash && (
          <>
            {" "}
            Transform receipt <code className="mono">{latest.transformReceiptHash.slice(0, 16)}</code>
          </>
        )}
      </p>

      {error && (
        <RouteEmptyState
          icon="data"
          title="Data profile unavailable"
          description={`The latest profile could not be loaded: ${error}`}
          actionLabel="Return to Live Workflow"
        />
      )}
      {!error && !profile && (
        <RouteEmptyState
          icon="data"
          title="No data profile yet"
          description="Start or select a run to inspect split health, feature coverage, label balance, and the frozen transform used by every experiment."
        />
      )}

      {profile && (
        <>
          <section style={{ ...cardStyle, marginTop: "var(--space-6)" }}>
            <p style={sectionHeading}>Split overview</p>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
              <thead>
                <tr>
                  <th style={th}>Split</th>
                  <th style={th}>Rows</th>
                  <th style={th}>Users</th>
                  <th style={th}>Videos</th>
                  <th style={th}>long_view rate</th>
                </tr>
              </thead>
              <tbody>
                {splitStats.map((raw, index) => {
                  const row = asRecord(raw);
                  return (
                    <tr key={index}>
                      <td style={td}>{stringOf(row, "split")}</td>
                      <td style={td} className="tabular">{numberOf(row, "rows")?.toLocaleString() ?? "-"}</td>
                      <td style={td} className="tabular">{numberOf(row, "users")?.toLocaleString() ?? "-"}</td>
                      <td style={td} className="tabular">{numberOf(row, "videos")?.toLocaleString() ?? "-"}</td>
                      <td style={td} className="tabular">{((numberOf(row, "long_view_rate") ?? 0) * 100).toFixed(1)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          <section style={{ ...cardStyle, marginTop: "var(--space-5)" }}>
            <p style={sectionHeading}>Users by label mix (zero, mixed, or all positive)</p>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
              <thead>
                <tr>
                  <th style={th}>Split</th>
                  <th style={th}>Group</th>
                  <th style={th}>Users</th>
                </tr>
              </thead>
              <tbody>
                {labelGroups.map((raw, index) => {
                  const row = asRecord(raw);
                  return (
                    <tr key={index}>
                      <td style={td}>{stringOf(row, "split")}</td>
                      <td style={td}>{stringOf(row, "label_group")}</td>
                      <td style={td} className="tabular">{numberOf(row, "users")?.toLocaleString() ?? "-"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          <section style={{ ...cardStyle, marginTop: "var(--space-5)" }}>
            <p style={sectionHeading}>Interactions per user</p>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
              <thead>
                <tr>
                  <th style={th}>Split</th>
                  <th style={th}>Min</th>
                  <th style={th}>Median</th>
                  <th style={th}>Mean</th>
                  <th style={th}>P95</th>
                  <th style={th}>Max</th>
                </tr>
              </thead>
              <tbody>
                {interactions.map((raw, index) => {
                  const row = asRecord(raw);
                  return (
                    <tr key={index}>
                      <td style={td}>{stringOf(row, "split")}</td>
                      <td style={td} className="tabular">{numberOf(row, "min") ?? "-"}</td>
                      <td style={td} className="tabular">{numberOf(row, "median") ?? "-"}</td>
                      <td style={td} className="tabular">{numberOf(row, "mean")?.toFixed(1) ?? "-"}</td>
                      <td style={td} className="tabular">{numberOf(row, "p95") ?? "-"}</td>
                      <td style={td} className="tabular">{numberOf(row, "max") ?? "-"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-5)", marginTop: "var(--space-5)" }}>
            <section style={cardStyle}>
              <p style={sectionHeading}>Missing values by field</p>
              <dl className="tabular" style={{ fontSize: 12, display: "grid", gridTemplateColumns: "1fr auto", gap: "var(--space-1) var(--space-3)" }}>
                {Object.entries(missing ?? {}).map(([key, value]) => (
                  <div key={key} style={{ display: "contents" }}>
                    <dt style={{ color: "var(--text-2)" }}>{key}</dt>
                    <dd style={{ margin: 0, textAlign: "right" }}>{typeof value === "number" ? value.toLocaleString() : "-"}</dd>
                  </div>
                ))}
              </dl>
            </section>
            <section style={cardStyle}>
              <p style={sectionHeading}>Field cardinality</p>
              <dl className="tabular" style={{ fontSize: 12, display: "grid", gridTemplateColumns: "1fr auto", gap: "var(--space-1) var(--space-3)" }}>
                {Object.entries(cardinalities ?? {}).map(([key, value]) => (
                  <div key={key} style={{ display: "contents" }}>
                    <dt style={{ color: "var(--text-2)" }}>{key}</dt>
                    <dd style={{ margin: 0, textAlign: "right" }}>{typeof value === "number" ? value.toLocaleString() : "-"}</dd>
                  </div>
                ))}
              </dl>
            </section>
          </div>

          <section style={{ ...cardStyle, marginTop: "var(--space-5)" }}>
            <p style={sectionHeading}>Watch-time censoring and duplicate exposures</p>
            <div style={{ display: "flex", gap: "var(--space-6)", fontSize: 12.5, flexWrap: "wrap" }}>
              <div>
                <strong>{numberOf(censoring, "rows")?.toLocaleString() ?? "-"}</strong>
                <div style={{ color: "var(--text-2)" }}>Rows evaluated</div>
              </div>
              <div>
                <strong>{numberOf(censoring, "completed_or_censored")?.toLocaleString() ?? "-"}</strong>
                <div style={{ color: "var(--text-2)" }}>play_time_ms &gt;= duration_ms</div>
              </div>
              <div>
                <strong>{((numberOf(censoring, "median_watch_fraction") ?? 0) * 100).toFixed(1)}%</strong>
                <div style={{ color: "var(--text-2)" }}>Median watch fraction</div>
              </div>
              <div>
                <strong>{((duplicateRate ?? 0) * 100).toFixed(2)}%</strong>
                <div style={{ color: "var(--text-2)" }}>Duplicate (user, video, date) exposures</div>
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

const cardStyle: CSSProperties = {
  background: "var(--surface-1)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-lg)",
  boxShadow: "var(--shadow-card)",
  padding: "var(--space-5)",
};
const sectionHeading: CSSProperties = {
  fontSize: 12,
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  color: "var(--text-2)",
  marginBottom: "var(--space-3)",
};
const th: CSSProperties = { textAlign: "left", padding: "var(--space-2) var(--space-4) var(--space-2) 0", borderBottom: "1px solid var(--ink-3)" };
const td: CSSProperties = { padding: "var(--space-2) var(--space-4) var(--space-2) 0", borderBottom: "1px solid var(--ink-2)" };
