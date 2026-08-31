import { useMemo, type CSSProperties } from "react";
import { RouteEmptyState } from "../components/RouteEmptyState";
import { selectAutonomyTimeline, type TimelineRow } from "../liveworkflow/selectors";
import { useRunStore, type ObserverNotice } from "../liveworkflow/runStore";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** `elapsedMs` -> `M:SS`, matching the wording in UI_changes.md #10's example
 * ("Still running after 5:00 -- ..."). */
function formatDuration(elapsedMs: number): string {
  const totalSeconds = Math.max(0, Math.round(elapsedMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

/** Builds the plain-language observer message for one notice row, following
 * UI_changes.md #10's exact wording pattern: cite the granular backend
 * stage/event type when known, otherwise say plainly that none has arrived
 * yet rather than guessing a substage. */
function noticeMessage(notice: ObserverNotice): string {
  const duration = formatDuration(notice.elapsedMs);
  if (!notice.stage || !notice.eventType) {
    return notice.stillRunning
      ? `${notice.componentLabel} is still running; no terminal event has been received.`
      : `${notice.componentLabel} finished after ${duration}; no terminal event was received.`;
  }
  const detail = `${notice.stage} / ${notice.eventType}${notice.summary ? `: ${notice.summary}` : ""}`;
  return notice.stillRunning
    ? `Still running after ${duration} \u2014 ${notice.componentLabel} is currently at ${detail}.`
    : `${notice.componentLabel} finished after ${duration} \u2014 last update: ${detail}.`;
}

/** A local union so the merged, chronologically sorted list can carry both
 * real ledger rows and UI-only observer notices without changing
 * `TimelineRow`'s shape or `selectAutonomyTimeline`'s behavior (UI_changes.md
 * #10: "Update the timeline selector and row type to support both ... Sort
 * them chronologically", done here rather than in the shared selector so the
 * ledger-only selector stays reusable elsewhere). */
type LogRow = { kind: "event"; key: string; occurredAt: string; row: TimelineRow } | { kind: "notice"; key: string; occurredAt: string; row: ObserverNotice };

export function AutonomyLog() {
  const events = useRunStore((state) => state.events);
  const observerNotices = useRunStore((state) => state.observerNotices);
  const rows = useMemo(() => selectAutonomyTimeline(events), [events]);
  const logRows = useMemo<LogRow[]>(() => {
    const eventRows: LogRow[] = rows.map((row) => ({ kind: "event", key: `event-${row.sequence}`, occurredAt: row.occurredAt, row }));
    const noticeRows: LogRow[] = observerNotices.map((row) => ({ kind: "notice", key: `notice-${row.id}`, occurredAt: row.createdAt, row }));
    return [...eventRows, ...noticeRows].sort((a, b) => new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime());
  }, [rows, observerNotices]);

  return (
    <div className="autonomy-log">
      <header className="autonomy-log__header">
        <h1>Autonomy Log</h1>
        <p>
          Chronological evidence for every decision, including the exact model family selected, validated code outcome,
          training result, recovery, and hardware decision. “Observer” rows are monitoring updates, not ledger events.
        </p>
      </header>

      <div className="autonomy-log__surface">
        {logRows.length === 0 ? (
          <RouteEmptyState
            icon="autonomy"
            title="No run evidence yet"
            description="Start or select a session to record stage decisions, outcomes, failures, recoveries, and monitoring updates in one chronological view."
          />
        ) : (
          <table className="data-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <caption className="visually-hidden">Chronological log of every stage action and outcome in this run, including observer monitoring updates</caption>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--text-2)" }}>
                <th scope="col" style={th}>Time</th>
                <th scope="col" style={th}>Sequence</th>
                <th scope="col" style={th}>Stage</th>
                <th scope="col" style={th}>Method</th>
                <th scope="col" style={th}>Action</th>
                <th scope="col" style={th}>Status</th>
              </tr>
            </thead>
            <tbody>
              {logRows.map((entry) =>
                entry.kind === "event" ? (
                  <tr key={entry.key}>
                    <td className="mono tabular" style={td}>{formatTime(entry.row.occurredAt)}</td>
                    <td className="mono tabular" style={td}>{entry.row.sequence}</td>
                    <td style={td}>{entry.row.componentLabel}</td>
                    <td className="mono" style={td}>{entry.row.method ?? "—"}</td>
                    <td style={{ ...td, color: "var(--text-1)" }}>{entry.row.action}</td>
                    <td className="mono" style={td}>{entry.row.status}</td>
                  </tr>
                ) : (
                  <tr key={entry.key} style={noticeRow}>
                    <td className="mono tabular" style={td}>{formatTime(entry.row.createdAt)}</td>
                    <td className="mono tabular" style={td}>
                      <span style={noticeBadge}>{entry.row.stillRunning ? "Observer" : "Monitoring"}</span>
                    </td>
                    <td style={td}>{entry.row.componentLabel}</td>
                    <td className="mono" style={td}>Monitoring</td>
                    <td style={{ ...td, color: "var(--text-1)" }}>{noticeMessage(entry.row)}</td>
                    <td className="mono" style={td}>
                      {entry.row.stillRunning ? "Still running" : "Finished"} · {formatDuration(entry.row.elapsedMs)}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

const th: CSSProperties = { padding: "var(--space-3) var(--space-5)", borderBottom: "1px solid var(--border)" };
const td: CSSProperties = { padding: "var(--space-3) var(--space-5)", borderBottom: "1px solid var(--surface-2)" };

/** Observer/monitoring rows get a left accent bar plus a tinted background
 * (reusing the existing "attention" status tokens from tokens.css) so they
 * read as visually distinct from real ledger rows at a glance, per
 * UI_changes.md #10. */
const noticeRow: CSSProperties = {
  background: "var(--status-attention-glow)",
  boxShadow: "inset 1px 0 0 var(--status-attention)",
};

const noticeBadge: CSSProperties = {
  display: "inline-block",
  padding: "2px 7px",
  borderRadius: "999px",
  fontSize: 10,
  fontWeight: 600,
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  color: "var(--status-attention)",
  background: "var(--surface-1)",
  border: "1px solid var(--status-attention)",
};
