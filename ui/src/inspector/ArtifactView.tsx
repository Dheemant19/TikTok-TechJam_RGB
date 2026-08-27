import { useState } from "react";
import { useArtifact } from "@/api/queries";
import styles from "./Inspector.module.css";

const REDACTED_TEXT = "Hidden to protect data and credentials";

interface ArtifactViewProps {
  artifactId: string;
}

/**
 * Renders one artifact by its actual media type. Redaction is applied on the
 * backend (server.py `redact`); this component only displays whatever content
 * the server returned — it never hides fields on its own (Plan_UI.md #3.4).
 */
export function ArtifactView({ artifactId }: ArtifactViewProps) {
  const { data, isLoading, isError } = useArtifact(artifactId);
  const [showRaw, setShowRaw] = useState(false);
  const [search, setSearch] = useState("");

  if (isLoading) return <p className="text-small">Loading artifact…</p>;
  if (isError || !data) return <p className="text-small">This artifact could not be loaded.</p>;

  if (data.content === REDACTED_TEXT) {
    return <p className={styles.redacted}>{REDACTED_TEXT}</p>;
  }

  if (data.media_type === "text/x-diff" && typeof data.content === "string") {
    return (
      <pre className={styles.diff} aria-label="Unified diff">
        {data.content.split("\n").map((line, index) => (
          <span
            key={index}
            className={line.startsWith("+") ? styles.diffAdd : line.startsWith("-") ? styles.diffDel : undefined}
          >
            {line}
            {"\n"}
          </span>
        ))}
      </pre>
    );
  }

  if (data.media_type === "text/plain" && typeof data.content === "string") {
    const lines = data.content.split("\n").filter((line) => !search || line.toLowerCase().includes(search.toLowerCase()));
    return (
      <div>
        <input
          type="search"
          placeholder="Search log…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className={styles.logSearch}
          aria-label="Search log content"
        />
        <pre className={styles.log}>{lines.join("\n") || "No matching lines."}</pre>
      </div>
    );
  }

  if (data.media_type === "application/json" && data.content && typeof data.content === "object") {
    const entries = Object.entries(data.content as Record<string, unknown>);
    return (
      <div>
        <dl className={styles.fieldList}>
          {entries.map(([key, value]) => (
            <div key={key} className={styles.fieldRow}>
              <dt>{key}</dt>
              <dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd>
            </div>
          ))}
        </dl>
        <button type="button" className={styles.rawToggle} onClick={() => setShowRaw((value) => !value)}>
          {showRaw ? "Hide raw JSON" : "Show raw JSON"}
        </button>
        {showRaw && <pre className={styles.log}>{JSON.stringify(data.content, null, 2)}</pre>}
      </div>
    );
  }

  // Binary/checkpoint artifacts: metadata plus checksum only.
  return (
    <dl className={styles.fieldList}>
      <div className={styles.fieldRow}>
        <dt>Type</dt>
        <dd>{data.media_type}</dd>
      </div>
      <div className={styles.fieldRow}>
        <dt>Checksum (SHA-256)</dt>
        <dd className={styles.mono}>{data.content_hash}</dd>
      </div>
      {data.row_count !== null && (
        <div className={styles.fieldRow}>
          <dt>Rows</dt>
          <dd>{data.row_count.toLocaleString()}</dd>
        </div>
      )}
    </dl>
  );
}
