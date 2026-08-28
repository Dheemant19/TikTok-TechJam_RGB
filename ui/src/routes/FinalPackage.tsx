import { useState } from "react";

export function FinalPackage() {
  const [confirmText, setConfirmText] = useState("");
  const sessionId = "sess-2026-08-27-kuairand-01";
  const ready = confirmText === sessionId;

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "var(--space-6)", maxWidth: 680 }}>
      <h1 style={{ fontSize: 18, marginBottom: "var(--space-1)" }}>Final Package</h1>
      <p style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 0 }}>
        Packaging freezes the research frontier. This has not run yet in this session.
      </p>

      <dl
        className="mono"
        style={{
          fontSize: 12.5,
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          gap: "var(--space-2) var(--space-4)",
          marginTop: "var(--space-5)",
          background: "var(--surface-1)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-lg)",
          boxShadow: "var(--shadow-card)",
          padding: "var(--space-5)",
        }}
      >
        <dt style={{ color: "var(--text-2)" }}>session_id</dt>
        <dd style={{ margin: 0 }}>{sessionId}</dd>
        <dt style={{ color: "var(--text-2)" }}>validation_best</dt>
        <dd style={{ margin: 0, color: "var(--text-2)" }}>not yet selected</dd>
        <dt style={{ color: "var(--text-2)" }}>clean_replay</dt>
        <dd style={{ margin: 0, color: "var(--text-2)" }}>pending</dd>
        <dt style={{ color: "var(--text-2)" }}>submission_schema</dt>
        <dd style={{ margin: 0, color: "var(--text-2)" }}>row_id,user_id,video_id,score</dd>
      </dl>

      <div style={{ marginTop: "var(--space-6)", borderTop: "1px solid var(--border)", paddingTop: "var(--space-5)" }}>
        <label htmlFor="confirm-session" style={{ display: "block", fontSize: 12, color: "var(--text-1)", marginBottom: "var(--space-2)" }}>
          Type the session ID to build the final package. This is irreversible once the hidden-test evaluation runs.
        </label>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <input
            id="confirm-session"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder={sessionId}
            className="mono"
            style={{
              flex: 1,
              background: "var(--ink-1)",
              border: "1px solid var(--ink-3)",
              borderRadius: "var(--radius-sm)",
              color: "var(--text-0)",
              padding: "var(--space-2) var(--space-3)",
              fontSize: 12.5,
            }}
          />
          <button
            disabled={!ready}
            style={{
              background: ready ? "var(--status-success)" : "var(--ink-2)",
              color: ready ? "#0d1a0d" : "var(--text-2)",
              border: "1px solid var(--ink-3)",
              borderRadius: "var(--radius-sm)",
              padding: "var(--space-2) var(--space-4)",
              fontSize: 12.5,
              fontWeight: 600,
              cursor: ready ? "pointer" : "not-allowed",
            }}
          >
            Build package
          </button>
        </div>
      </div>
    </div>
  );
}
