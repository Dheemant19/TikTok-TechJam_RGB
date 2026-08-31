import { useMemo } from "react";
import { RouteEmptyState } from "../components/RouteEmptyState";
import { selectResearchEvidence } from "../liveworkflow/selectors";
import { useRunStore } from "../liveworkflow/runStore";

export function ResearchLibrary() {
  const events = useRunStore((state) => state.events);
  const { cards, missingEvidence } = useMemo(() => selectResearchEvidence(events), [events]);

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "var(--space-6)", maxWidth: 1200, width: "100%", margin: "0 auto" }}>
      <h1 style={{ fontFamily: "var(--font-display)", fontSize: 32, fontWeight: 560, letterSpacing: "-0.012em", marginBottom: "var(--space-2)" }}>Research Library</h1>
      <p style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 0 }}>
        Evidence retrieved by the Research Knowledge MCP, using curated seed papers plus bounded API enrichment.
      </p>

      {cards.length === 0 ? (
        <RouteEmptyState
          icon="research"
          title="No research evidence yet"
          description="Start a run to collect the papers, methods, and counter-evidence the research agent uses to justify its next experiment."
        />
      ) : (
        <ol
          style={{
            listStyle: "none",
            margin: "var(--space-5) 0 0",
            padding: 0,
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))",
            gap: "var(--space-4)",
          }}
        >
          {cards.map((doc) => (
            <li
              key={`${doc.kind}-${doc.id}`}
              style={{
                background: "var(--surface-1)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-lg)",
                boxShadow: "var(--shadow-card)",
                padding: "var(--space-4) var(--space-5)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-3)" }}>
                <h2 style={{ fontSize: 13.5, margin: 0 }}>{doc.title}</h2>
                <span className="mono" style={{ fontSize: 10.5, color: "var(--text-2)", flexShrink: 0 }}>
                  {doc.sourceMode}
                </span>
              </div>
              <p style={{ fontSize: 12.5, color: "var(--text-1)", margin: "var(--space-2) 0" }}>{doc.relevanceNotes}</p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)", alignItems: "center" }}>
                <span
                  className="mono"
                  style={{
                    fontSize: 10.5,
                    color: doc.kind === "supporting" ? "var(--status-success)" : "var(--status-attention)",
                    background: "var(--surface-2)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-sm)",
                    padding: "1px 6px",
                  }}
                >
                  {doc.kind}
                </span>
                <span
                  className="mono"
                  title="Where this evidence was retrieved from: the curated seed bank or a live Hugging Face Papers fetch."
                  style={{
                    fontSize: 10.5,
                    color: "var(--text-2)",
                    background: "var(--surface-2)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-sm)",
                    padding: "1px 6px",
                  }}
                >
                  {doc.trustTierLabel}
                </span>
                {doc.hasGithubCode && (
                  <a
                    className="mono"
                    href={doc.githubUrl ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      fontSize: 10.5,
                      color: "var(--text-1)",
                      background: "var(--surface-2)",
                      border: "1px solid var(--border)",
                      borderRadius: "var(--radius-sm)",
                      padding: "1px 6px",
                      textDecoration: "none",
                    }}
                  >
                    GitHub code
                  </a>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}

      {missingEvidence.length > 0 && (
        <section style={{ marginTop: "var(--space-5)" }}>
          <p style={{ fontSize: 12, color: "var(--text-2)", marginBottom: "var(--space-2)" }}>Gaps noted by the research card</p>
          <ul style={{ fontSize: 12.5, color: "var(--text-1)", paddingLeft: "var(--space-5)" }}>
            {missingEvidence.map((note, index) => (
              <li key={index}>{note}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
