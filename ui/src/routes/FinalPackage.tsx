import { useState } from "react";
import { field } from "../api/json";
import { useRunStore } from "../liveworkflow/runStore";

function textOf(value: unknown, fallback = "not yet selected"): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

export function FinalPackage() {
  const sessionId = useRunStore((state) => state.sessionId);
  const snapshot = useRunStore((state) => state.snapshot);
  const packaging = useRunStore((state) => state.packaging);
  const packageResult = useRunStore((state) => state.packageResult);
  const packageError = useRunStore((state) => state.packageError);
  const packageRun = useRunStore((state) => state.packageRun);
  const [confirmText, setConfirmText] = useState("");

  const canPackage = Boolean(sessionId) && (snapshot?.allowed_actions.includes("package") ?? false) && !packageResult;
  const ready = canPackage && confirmText === sessionId;
  const frontier = snapshot?.frontier;

  const manifestHash = packageResult ? textOf(field(packageResult, "manifest_hash")) : null;
  const testPredictionPasses = packageResult ? field(packageResult, "test_prediction_passes") : null;
  const eventChainValid = packageResult ? field(packageResult, "event_chain_valid") : null;

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "var(--space-6)", maxWidth: 1200, width: "100%", margin: "0 auto" }}>
      <h1 style={{ fontFamily: "var(--font-display)", fontSize: 32, fontWeight: 560, letterSpacing: "-0.012em", marginBottom: "var(--space-2)" }}>Final Package</h1>
      <p style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 0 }}>
        {packageResult
          ? "Packaging is complete. This boundary is one-way and cannot be reopened by the UI."
          : sessionId
            ? "Packaging freezes the research frontier. Available once the run converges or stops on budget."
            : "No session attached. Start or attach to a run from Live Workflow first."}
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
        <dd style={{ margin: 0 }}>{sessionId ?? "no session attached"}</dd>
        <dt style={{ color: "var(--text-2)" }}>validation_best</dt>
        <dd style={{ margin: 0, color: frontier?.validation_best ? "var(--text-0)" : "var(--text-2)" }}>{textOf(frontier?.validation_best)}</dd>
        <dt style={{ color: "var(--text-2)" }}>stable_fallback</dt>
        <dd style={{ margin: 0, color: frontier?.stable_fallback ? "var(--text-0)" : "var(--text-2)" }}>{textOf(frontier?.stable_fallback)}</dd>
        <dt style={{ color: "var(--text-2)" }}>frontier_locked</dt>
        <dd style={{ margin: 0 }}>{frontier?.locked ? "yes" : "no"}</dd>
        <dt style={{ color: "var(--text-2)" }}>submission_schema</dt>
        <dd style={{ margin: 0 }}>row_id,user_id,video_id,score</dd>
        {packageResult && (
          <>
            <dt style={{ color: "var(--text-2)" }}>manifest_hash</dt>
            <dd style={{ margin: 0 }}>{manifestHash}</dd>
            <dt style={{ color: "var(--text-2)" }}>test_prediction_passes</dt>
            <dd style={{ margin: 0 }}>{typeof testPredictionPasses === "number" ? testPredictionPasses : "-"}</dd>
            <dt style={{ color: "var(--text-2)" }}>event_chain_valid</dt>
            <dd style={{ margin: 0 }}>{typeof eventChainValid === "boolean" ? (eventChainValid ? "yes" : "no") : "-"}</dd>
          </>
        )}
      </dl>

      {packageError && (
        <p style={{ marginTop: "var(--space-4)", fontSize: 12.5, color: "var(--status-attention)" }}>{packageError}</p>
      )}

      {!packageResult && (
        <div style={{ marginTop: "var(--space-6)", borderTop: "1px solid var(--border)", paddingTop: "var(--space-5)" }}>
          <label htmlFor="confirm-session" style={{ display: "block", fontSize: 12, color: "var(--text-1)", marginBottom: "var(--space-2)" }}>
            Type the session ID to build the final package. This is irreversible once the hidden-test evaluation runs.
          </label>
          <div style={{ display: "flex", gap: "var(--space-2)" }}>
            <input
              id="confirm-session"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder={sessionId ?? "session id"}
              disabled={!canPackage}
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
              type="button"
              disabled={!ready || packaging}
              onClick={() => packageRun()}
              style={{
                background: ready ? "var(--status-success)" : "var(--ink-2)",
                color: ready ? "#0d1a0d" : "var(--text-2)",
                border: "1px solid var(--ink-3)",
                borderRadius: "var(--radius-sm)",
                padding: "var(--space-2) var(--space-4)",
                fontSize: 12.5,
                fontWeight: 600,
                cursor: ready && !packaging ? "pointer" : "not-allowed",
              }}
            >
              {packaging ? "Building..." : "Build package"}
            </button>
          </div>
          {!canPackage && sessionId && (
            <p style={{ fontSize: 11.5, color: "var(--text-2)", marginTop: "var(--space-2)" }}>
              Packaging unlocks once the watchdog reports convergence or a budget stop with a validation-best result.
            </p>
          )}
        </div>
      )}
    </div>
  );
}


