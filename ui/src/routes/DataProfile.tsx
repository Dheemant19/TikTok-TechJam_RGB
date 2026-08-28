import type { CSSProperties } from "react";

const SPLITS = [
  { split: "Train (04/08–04/21)", rows: 1_140_000, positiveRate: 0.312 },
  { split: "Validation (04/22–04/28)", rows: 462_000, positiveRate: 0.298 },
  { split: "Test (04/29–05/08)", rows: 660_000, positiveRate: 0.287 },
];

const USER_MIX = [
  { label: "All-negative users", pct: 27.1 },
  { label: "Mixed (0 < positives < exposures)", pct: 63.7 },
  { label: "All-positive users", pct: 9.2 },
];

export function DataProfile() {
  const maxRows = Math.max(...SPLITS.map((s) => s.rows));

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "var(--space-6)", maxWidth: 1200, width: "100%", margin: "0 auto" }}>
      <h1 style={{ fontSize: 18, marginBottom: "var(--space-1)" }}>Data Profile</h1>
      <p style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 0 }}>
        Frozen train-only transform · row counts and label prevalence by split
      </p>

      <section style={{ ...cardStyle, marginTop: "var(--space-6)" }}>
        <h2 style={sectionHeading}>Split row counts</h2>
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          {SPLITS.map((s) => (
            <div key={s.split} style={{ display: "grid", gridTemplateColumns: "220px 1fr 90px", gap: "var(--space-3)", alignItems: "center" }}>
              <span style={{ fontSize: 12.5 }}>{s.split}</span>
              <div style={{ background: "var(--ink-2)", borderRadius: "var(--radius-sm)", height: 10, overflow: "hidden" }}>
                <div
                  style={{
                    width: `${(s.rows / maxRows) * 100}%`,
                    height: "100%",
                    background: "var(--status-success)",
                  }}
                />
              </div>
              <span className="mono tabular" style={{ fontSize: 12, textAlign: "right" }}>
                {s.rows.toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      </section>

      <section style={{ ...cardStyle, marginTop: "var(--space-5)" }}>
        <h2 style={sectionHeading}>long_view prevalence by user mix (test split)</h2>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
          <thead>
            <tr style={{ color: "var(--text-2)", textAlign: "left" }}>
              <th scope="col" style={th}>
                User group
              </th>
              <th scope="col" style={th}>
                Share of test users
              </th>
            </tr>
          </thead>
          <tbody>
            {USER_MIX.map((u) => (
              <tr key={u.label}>
                <td style={td}>{u.label}</td>
                <td className="mono tabular" style={td}>
                  {u.pct.toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p style={{ fontSize: 11.5, color: "var(--text-2)", marginTop: "var(--space-3)" }}>
          All-negative users score 0.0 on nDCG@5 and are included in the average; GAUC only evaluates the mixed group.
        </p>
      </section>

      <section style={{ ...cardStyle, marginTop: "var(--space-5)" }}>
        <h2 style={sectionHeading}>Transform lineage</h2>
        <dl className="mono" style={{ fontSize: 12, display: "grid", gridTemplateColumns: "auto 1fr", gap: "var(--space-2) var(--space-4)" }}>
          <dt style={{ color: "var(--text-2)" }}>source_hash</dt>
          <dd style={{ margin: 0 }}>a13f9e2…</dd>
          <dt style={{ color: "var(--text-2)" }}>transform_hash</dt>
          <dd style={{ margin: 0 }}>6f1a2c4…</dd>
          <dt style={{ color: "var(--text-2)" }}>materialized_hash</dt>
          <dd style={{ margin: 0 }}>d90b117…</dd>
        </dl>
      </section>
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
const th: CSSProperties = { padding: "var(--space-2) var(--space-4) var(--space-2) 0", borderBottom: "1px solid var(--ink-3)" };
const td: CSSProperties = { padding: "var(--space-2) var(--space-4) var(--space-2) 0", borderBottom: "1px solid var(--ink-2)" };
