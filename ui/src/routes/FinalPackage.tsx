import { useMemo, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { asRecord, field } from "../api/json";
import type { RunEventDTO } from "../api/types";
import { selectExperiments } from "../liveworkflow/selectors";
import { useRunStore } from "../liveworkflow/runStore";

function textOf(value: unknown, fallback = "Not available"): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}


function duplicatePredictionRuns(events: RunEventDTO[]): string[] {
  const firstRunByHash = new Map<string, string>();
  const duplicates = new Set<string>();
  for (const event of [...events].sort((left, right) => left.sequence - right.sequence)) {
    if (event.component_id !== "evaluator" || event.event_type !== "metric") continue;
    const receipt = asRecord(field(asRecord(event.payload), "receipt"));
    const predictionHash = textOf(field(receipt, "prediction_artifact_id"), "");
    if (!predictionHash) continue;
    const firstRun = firstRunByHash.get(predictionHash);
    if (firstRun && firstRun !== event.run_id) {
      duplicates.add(firstRun);
      duplicates.add(event.run_id);
    } else {
      firstRunByHash.set(predictionHash, event.run_id);
    }
  }
  return [...duplicates];
}

export function FinalPackage() {
  const sessionId = useRunStore((state) => state.sessionId);
  const snapshot = useRunStore((state) => state.snapshot);
  const events = useRunStore((state) => state.events);
  const packaging = useRunStore((state) => state.packaging);
  const packageResult = useRunStore((state) => state.packageResult);
  const packageError = useRunStore((state) => state.packageError);
  const packageRun = useRunStore((state) => state.packageRun);
  const attachedSnapshot = snapshot?.session_id === sessionId ? snapshot : null;

  const rows = useMemo(() => selectExperiments(events), [events]);
  const duplicateRuns = useMemo(() => duplicatePredictionRuns(events), [events]);
  const baseline = rows.find((row) => row.status === "baseline");
  const frontier = attachedSnapshot?.frontier;
  const winner = packageResult
    ? textOf(field(packageResult, "validation_best"), textOf(frontier?.validation_best, ""))
    : textOf(frontier?.validation_best, "");
  const experimentId = packageResult ? textOf(field(packageResult, "experiment_id"), "") : "";
  const selected = winner === "B0"
    ? baseline
    : rows.find((row) => row.id === experimentId || row.runId === winner);
  const selectedLabel = winner === "B0"
    ? "Official FM baseline (B0)"
    : selected?.label ?? (winner ? "Validation-best experiment" : "Selection pending");
  const primaryDelta = selected?.primary !== null
    && selected?.primary !== undefined
    && baseline?.primary !== null
    && baseline?.primary !== undefined
    ? selected.primary - baseline.primary
    : null;
  const isBaselinePackage = winner === "B0";
  const hasIntegrityWarning = duplicateRuns.length > 0;
  const canPackage = Boolean(sessionId)
    && !attachedSnapshot?.finalized
    && !attachedSnapshot?.cancelled
    && (
      Boolean(attachedSnapshot?.allowed_actions.includes("package"))
      || (
        attachedSnapshot?.status === "succeeded"
        && attachedSnapshot.frontier.locked
        && Boolean(attachedSnapshot.frontier.validation_best)
      )
    )
    && !packageResult;

  const packageSessionId = packageResult
    ? textOf(field(packageResult, "session_id"), sessionId ?? "")
    : sessionId ?? "";
  const predictionsPath = packageResult
    ? textOf(field(packageResult, "predictions"), "")
    : "";
  const checkpointPath = packageResult
    ? textOf(field(packageResult, "checkpoint"), "")
    : "";
  const pathSeparatorIndex = Math.max(
    predictionsPath.lastIndexOf("/"),
    predictionsPath.lastIndexOf("\\"),
  );
  const packageDirectory = pathSeparatorIndex >= 0
    ? predictionsPath.slice(0, pathSeparatorIndex)
    : predictionsPath;
  const separator = predictionsPath.includes("\\") ? "\\" : "/";
  const manifestPath = packageDirectory ? `${packageDirectory}${separator}manifest.json` : "";
  const schemaCheck = packageResult
    ? asRecord(field(packageResult, "schema_check"))
    : undefined;
  const schemaPassed = field(schemaCheck, "exit_code") === 0;
  const eventChainValid = packageResult
    ? field(packageResult, "event_chain_valid") === true
    : false;

  const packageStatus = hasIntegrityWarning
    ? {
        title: "Package blocked by an integrity warning",
        detail: `This session contains byte-identical outputs from ${duplicateRuns.length} experiment runs. The CSV passed its format check, but this result should not be submitted.`,
        color: "var(--status-failed)",
      }
    : isBaselinePackage
      ? {
          title: "Baseline package ready",
          detail: "The official FM baseline was selected because no experiment cleared the required validation improvement. The files are valid, but this is not an improved entry.",
          color: "var(--status-attention)",
        }
      : {
          title: "Validation-best package ready",
          detail: "The selected checkpoint produced a test prediction file, and the official starter-kit format check passed. Test ranking quality is not measured during packaging.",
          color: "var(--status-success)",
        };

  return (
    <div style={pageStyle}>
      <h1 style={headingStyle}>Final Package</h1>
      <p style={introStyle}>
        This page tells you what was selected, whether it is safe to submit, and where to get the submission file.
      </p>

      {packageResult ? (
        <>
          <section aria-live="polite" style={{ ...packageStatusStyle, borderColor: packageStatus.color }}>
            <div>
              <h2 style={packageStatusHeadingStyle}>{packageStatus.title}</h2>
              <p style={packageStatusDetailStyle}>{packageStatus.detail}</p>
            </div>
            <span style={{ ...statusPillStyle, color: packageStatus.color, borderColor: packageStatus.color }}>
              {hasIntegrityWarning ? "Blocked" : schemaPassed && eventChainValid ? "Verified" : "Review checks"}
            </span>
          </section>

          <section style={cardStyle}>
            <h2 style={sectionHeadingStyle}>What this package contains</h2>
            <div style={factsGridStyle}>
              <Fact label="Selected model" value={selectedLabel} />
              <Fact
                label="Validation primary"
                value={selected?.primary == null ? "Not available" : selected.primary.toFixed(4)}
              />
              <Fact
                label="Delta vs baseline"
                value={primaryDelta === null ? "Not available" : `${primaryDelta >= 0 ? "+" : ""}${primaryDelta.toFixed(4)}`}
              />
              <Fact label="Hidden-test result" value="Not scored here" />
              <Fact label="CSV format check" value={schemaPassed ? "Passed" : "Not confirmed"} />
              <Fact label="Audit event chain" value={eventChainValid ? "Valid" : "Not confirmed"} />
            </div>
          </section>

          <section style={cardStyle}>
            <h2 style={sectionHeadingStyle}>What to do next</h2>
            {hasIntegrityWarning ? (
              <div style={actionRowStyle}>
                <Link to="/" style={secondaryActionStyle}>Return to Live Workflow</Link>
                <p style={actionHelpStyle}>Restart the backend first, then start a new session. Do not use this CSV.</p>
              </div>
            ) : (
              <>
                <p style={actionHelpStyle}>
                  {isBaselinePackage
                    ? "Download predictions.csv only if you intend to use the official baseline. Keep manifest.json as the record of exactly what was packaged."
                    : "Download predictions.csv, then follow the organizer’s current submission instructions. The starter kit defines the CSV format and checker, but it does not name an upload destination. Keep manifest.json with your audit evidence."}
                </p>
                {packageSessionId && (
                  <div style={downloadRowStyle}>
                    <a
                      href={api.packageFileUrl(packageSessionId, "predictions.csv")}
                      download
                      style={primaryActionStyle}
                    >
                      Download predictions.csv
                    </a>
                    <a
                      href={api.packageFileUrl(packageSessionId, "manifest.json")}
                      download
                      style={secondaryActionStyle}
                    >
                      Download manifest.json
                    </a>
                  </div>
                )}
              </>
            )}
          </section>

          <details style={detailsStyle}>
            <summary style={summaryStyle}>Technical package details</summary>
            <dl className="tabular" style={detailGridStyle}>
              <dt style={termStyle}>Session</dt>
              <dd style={valueStyle}>{packageSessionId || "Not available"}</dd>
              <dt style={termStyle}>Package folder</dt>
              <dd style={pathValueStyle}>{packageDirectory || "Not available"}</dd>
              <dt style={termStyle}>Submission CSV</dt>
              <dd style={pathValueStyle}>{predictionsPath || "Not available"}</dd>
              <dt style={termStyle}>Manifest</dt>
              <dd style={pathValueStyle}>{manifestPath || "Not available"}</dd>
              <dt style={termStyle}>Checkpoint</dt>
              <dd style={pathValueStyle}>{checkpointPath || "Not available"}</dd>
              <dt style={termStyle}>Manifest hash</dt>
              <dd style={pathValueStyle}>{textOf(field(packageResult, "manifest_hash"))}</dd>
            </dl>
          </details>
        </>
      ) : (
        <>
          <section style={cardStyle}>
            <h2 style={sectionHeadingStyle}>Current selection</h2>
            <div style={factsGridStyle}>
              <Fact label="Session" value={sessionId ?? "No session attached"} />
              <Fact label="Artifact to package" value={selectedLabel} />
            </div>
            <p style={{ ...actionHelpStyle, marginTop: "var(--space-3)" }}>
              {sessionId
                ? "FlowState will freeze the validation-best checkpoint and create predictions.csv. This does not submit the file or score the test labels."
                : "Start or attach to a run from Live Workflow first."}
            </p>
          </section>

          <section style={cardStyle}>
            <h2 style={sectionHeadingStyle}>Build the package</h2>
            <p style={actionHelpStyle}>
              {canPackage
                ? `Ready to package ${selectedLabel} from the attached session.`
                : sessionId
                  ? "This session is still running. Packaging unlocks after convergence or the compute budget selects a validation-best result."
                  : "Attach a completed session to build its final package."}
            </p>
            <button
              type="button"
              disabled={!canPackage || packaging}
              onClick={() => packageRun()}
              style={{
                ...buildButtonStyle,
                marginTop: "var(--space-4)",
                background: canPackage ? "var(--status-success)" : "var(--surface-2)",
                color: canPackage ? "#0d1a0d" : "var(--text-2)",
                cursor: canPackage && !packaging ? "pointer" : "not-allowed",
              }}
            >
              {packaging ? "Building package..." : "Build final package"}
            </button>
          </section>
        </>
      )}

      {packageError && (
        <p role="alert" style={errorStyle}>{packageError}</p>
      )}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div style={factStyle}>
      <span style={factLabelStyle}>{label}</span>
      <strong className="tabular" style={factValueStyle}>{value}</strong>
    </div>
  );
}

const pageStyle: CSSProperties = {
  flex: 1,
  overflowY: "auto",
  padding: "var(--space-6)",
  maxWidth: 1200,
  width: "100%",
  margin: "0 auto",
};
const headingStyle: CSSProperties = {
  fontFamily: "var(--font-display)",
  fontSize: 32,
  fontWeight: 560,
  letterSpacing: "-0.012em",
  marginBottom: "var(--space-2)",
};
const introStyle: CSSProperties = {
  color: "var(--text-2)",
  fontSize: 12.5,
  marginTop: 0,
  maxWidth: "72ch",
};
const cardStyle: CSSProperties = {
  marginTop: "var(--space-4)",
  background: "var(--surface-1)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-lg)",
  boxShadow: "var(--shadow-card)",
  padding: "var(--space-5)",
};
const packageStatusStyle: CSSProperties = {
  ...cardStyle,
  border: "1px solid",
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-start",
  gap: "var(--space-4)",
};
const packageStatusHeadingStyle: CSSProperties = {
  fontFamily: "var(--font-display)",
  fontSize: 22,
  lineHeight: 1.25,
  margin: 0,
};
const packageStatusDetailStyle: CSSProperties = {
  color: "var(--text-1)",
  lineHeight: 1.6,
  maxWidth: "76ch",
  margin: "var(--space-2) 0 0",
};
const statusPillStyle: CSSProperties = {
  flex: "0 0 auto",
  border: "1px solid",
  borderRadius: 999,
  padding: "5px 10px",
  fontSize: 10.5,
  fontWeight: 800,
  letterSpacing: "0.04em",
};
const sectionHeadingStyle: CSSProperties = {
  fontSize: 16,
  fontWeight: 750,
  margin: "0 0 var(--space-3)",
};
const factsGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: "var(--space-3)",
};
const factStyle: CSSProperties = {
  background: "var(--surface-2)",
  borderRadius: "var(--radius-md)",
  padding: "var(--space-3)",
  minWidth: 0,
};
const factLabelStyle: CSSProperties = {
  display: "block",
  color: "var(--text-2)",
  fontSize: 11,
  fontWeight: 700,
  marginBottom: "var(--space-1)",
};
const factValueStyle: CSSProperties = {
  color: "var(--text-0)",
  fontSize: 13,
  overflowWrap: "anywhere",
};
const actionRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  flexWrap: "wrap",
  gap: "var(--space-3)",
};
const downloadRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "var(--space-2)",
  marginTop: "var(--space-4)",
};
const actionHelpStyle: CSSProperties = {
  color: "var(--text-1)",
  lineHeight: 1.6,
  margin: 0,
  maxWidth: "76ch",
};
const primaryActionStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  minHeight: 40,
  padding: "0 var(--space-4)",
  borderRadius: "var(--radius-sm)",
  background: "var(--primary)",
  color: "#fff",
  fontWeight: 700,
  textDecoration: "none",
};
const secondaryActionStyle: CSSProperties = {
  ...primaryActionStyle,
  background: "var(--surface-2)",
  color: "var(--text-0)",
  border: "1px solid var(--border-strong)",
};
const detailsStyle: CSSProperties = {
  ...cardStyle,
  padding: "var(--space-4) var(--space-5)",
};
const summaryStyle: CSSProperties = {
  cursor: "pointer",
  fontWeight: 700,
};
const detailGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(130px, auto) minmax(0, 1fr)",
  gap: "var(--space-2) var(--space-4)",
  margin: "var(--space-4) 0 0",
  fontSize: 12.5,
};
const termStyle: CSSProperties = { color: "var(--text-2)" };
const valueStyle: CSSProperties = { margin: 0 };
const pathValueStyle: CSSProperties = {
  ...valueStyle,
  overflowWrap: "anywhere",
};
const buildButtonStyle: CSSProperties = {
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-sm)",
  padding: "var(--space-2) var(--space-4)",
  fontSize: 12.5,
  fontWeight: 700,
};
const errorStyle: CSSProperties = {
  marginTop: "var(--space-4)",
  fontSize: 12.5,
  color: "var(--status-failed)",
};


