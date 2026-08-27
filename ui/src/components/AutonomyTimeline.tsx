import { NODE_REGISTRY } from "@/workflow/nodeRegistry";
import { STATUS_STYLES } from "@/workflow/statusStyles";
import type { ComponentId, RunEvent } from "@/api/types";
import styles from "./AutonomyTimeline.module.css";

interface AutonomyTimelineProps {
  events: RunEvent[];
  onSelectRow: (componentId: ComponentId, executionId: string) => void;
}

function durationLabel(event: RunEvent, startedAtByExecution: Map<string, string>): string {
  const startedAt = startedAtByExecution.get(event.execution_id);
  if (!startedAt) return "—";
  const seconds = Math.max(0, (new Date(event.occurred_at).getTime() - new Date(startedAt).getTime()) / 1000);
  return seconds < 1 ? "<1s" : `${seconds.toFixed(1)}s`;
}

/** Each row selects the corresponding node and execution attempt (Plan_UI.md #5.2). */
export function AutonomyTimeline({ events, onSelectRow }: AutonomyTimelineProps) {
  const startedAtByExecution = new Map<string, string>();
  for (const event of events) {
    if (!startedAtByExecution.has(event.execution_id)) startedAtByExecution.set(event.execution_id, event.occurred_at);
  }
  const rows = [...events].reverse().slice(0, 100);

  return (
    <div className={styles.wrapper}>
      <table className={styles.table}>
        <caption className="visually-hidden">Autonomy timeline: every recorded workflow action</caption>
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">Component</th>
            <th scope="col">Action</th>
            <th scope="col">Outcome</th>
            <th scope="col">Duration</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((event) => {
            const style = STATUS_STYLES[event.status];
            return (
              <tr key={event.event_id}>
                <td>
                  <button type="button" className={styles.rowButton} onClick={() => onSelectRow(event.component_id, event.execution_id)}>
                    {new Date(event.occurred_at).toLocaleTimeString()}
                  </button>
                </td>
                <td>{NODE_REGISTRY[event.component_id].label}</td>
                <td>{event.event_type}</td>
                <td style={{ color: `var(${style.colorVar})` }}>{style.label}</td>
                <td>{durationLabel(event, startedAtByExecution)}</td>
              </tr>
            );
          })}
          {rows.length === 0 && (
            <tr>
              <td colSpan={5} className="text-small">
                No events recorded yet for this session.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
