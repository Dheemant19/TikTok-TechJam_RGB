import type { RunEvent } from "@/api/types";
import styles from "./Inspector.module.css";

interface ImplementationDetailsProps {
  event: RunEvent;
}

/** Hashes, exact commands, and raw JSON — collapsed below plain-language fields. */
export function ImplementationDetails({ event }: ImplementationDetailsProps) {
  return (
    <details className={styles.details}>
      <summary>Implementation details</summary>
      <dl className={styles.fieldList}>
        <div className={styles.fieldRow}>
          <dt>Event hash</dt>
          <dd className={styles.mono}>{event.event_hash}</dd>
        </div>
        <div className={styles.fieldRow}>
          <dt>Execution ID</dt>
          <dd className={styles.mono}>{event.execution_id}</dd>
        </div>
        <div className={styles.fieldRow}>
          <dt>Stage / event type</dt>
          <dd>
            {event.stage} / {event.event_type}
          </dd>
        </div>
      </dl>
      <pre className={styles.log}>{JSON.stringify(event.payload, null, 2)}</pre>
    </details>
  );
}
