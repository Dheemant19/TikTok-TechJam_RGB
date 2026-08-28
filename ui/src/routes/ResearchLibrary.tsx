import { DEMO_RESEARCH } from "../data/demoFixture";

export function ResearchLibrary() {
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "var(--space-6)", maxWidth: 780 }}>
      <h1 style={{ fontSize: 18, marginBottom: "var(--space-1)" }}>Research Library</h1>
      <p style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 0 }}>
        Evidence retrieved by the Research Knowledge MCP — curated seed papers plus bounded API enrichment.
      </p>

      <ol style={{ listStyle: "none", margin: "var(--space-5) 0 0", padding: 0, display: "grid", gap: "var(--space-3)" }}>
        {DEMO_RESEARCH.map((doc) => (
          <li
            key={doc.id}
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
              <span className="mono tabular" style={{ fontSize: 12, color: "var(--text-2)", flexShrink: 0 }}>
                {doc.year}
              </span>
            </div>
            <p style={{ fontSize: 12.5, color: "var(--text-1)", margin: "var(--space-2) 0" }}>{doc.note}</p>
            <div style={{ display: "flex", gap: "var(--space-2)" }}>
              {doc.tags.map((tag) => (
                <span
                  key={tag}
                  className="mono"
                  style={{
                    fontSize: 10.5,
                    color: "var(--status-success)",
                    background: "var(--surface-2)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-sm)",
                    padding: "1px 6px",
                  }}
                >
                  {tag}
                </span>
              ))}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
