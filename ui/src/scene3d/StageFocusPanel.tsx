import { useEffect, useMemo, useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import { motion, AnimatePresence } from "motion/react";
import { X } from "lucide-react";
import { NODE_REGISTRY } from "@/workflow/nodeRegistry";
import { STATUS_STYLES } from "@/workflow/statusStyles";
import { ArtifactView } from "@/inspector/ArtifactView";
import { ImplementationDetails } from "@/inspector/ImplementationDetails";
import type { ComponentId, RunEvent } from "@/api/types";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import inspectorStyles from "@/inspector/Inspector.module.css";
import styles from "./StageFocusPanel.module.css";

const INPUT_EVENT_TYPES = new Set(["started", "queued"]);

interface StageFocusPanelProps {
  componentId: ComponentId;
  events: RunEvent[];
  onClose: () => void;
  focusExecutionId?: string | null;
}

/** The full-screen "this stage takes over" view — same data contract as the side Inspector, framed as an instrument readout instead of a panel. */
export function StageFocusPanel({ componentId, events, onClose, focusExecutionId }: StageFocusPanelProps) {
  const definition = NODE_REGISTRY[componentId];
  const reducedMotion = useReducedMotion();
  const attempts = useMemo(() => events.filter((event) => event.component_id === componentId), [events, componentId]);
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(focusExecutionId ?? null);

  useEffect(() => {
    if (focusExecutionId) setSelectedExecutionId(focusExecutionId);
  }, [focusExecutionId]);
  const executionIds = useMemo(() => [...new Set(attempts.map((event) => event.execution_id))], [attempts]);
  const activeExecutionId = selectedExecutionId ?? executionIds.at(-1) ?? null;
  const activeAttempts = attempts.filter((event) => event.execution_id === activeExecutionId);
  const latest = activeAttempts.at(-1) ?? attempts.at(-1);
  const style = latest ? STATUS_STYLES[latest.status] : STATUS_STYLES.waiting;

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <motion.div
      className={styles.panel}
      role="dialog"
      aria-label={`${definition.label} — stage detail`}
      initial={reducedMotion ? { opacity: 0 } : { opacity: 0, scale: 1.02 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={reducedMotion ? { opacity: 0 } : { opacity: 0, scale: 1.02 }}
      transition={reducedMotion ? { duration: 0.15 } : { type: "spring", bounce: 0, duration: 0.42 }}
    >
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}>{definition.secondaryLabel}</span>
          <h1>{definition.label}</h1>
        </div>
        <button type="button" className={`pressable ${styles.closeButton}`} onClick={onClose} aria-label="Return to pipeline overview">
          <X size={20} aria-hidden="true" />
          <span>Overview</span>
        </button>
      </header>

      <Tabs.Root defaultValue="summary" className={styles.tabsRoot}>
        <Tabs.List className={styles.tabsList} aria-label="Stage details">
          <Tabs.Trigger value="summary" className={styles.tabTrigger}>Summary</Tabs.Trigger>
          <Tabs.Trigger value="input" className={styles.tabTrigger}>Input</Tabs.Trigger>
          <Tabs.Trigger value="output" className={styles.tabTrigger}>Output</Tabs.Trigger>
          <Tabs.Trigger value="history" className={styles.tabTrigger}>History</Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="summary" className={styles.tabContent}>
          {latest ? (
            <>
              <p className={styles.statusLine} style={{ color: `var(${style.colorVar})` }}>{style.label}</p>
              <p className={styles.summaryText}>{latest.plain_summary}</p>
              <dl className={inspectorStyles.fieldList}>
                <div className={inspectorStyles.fieldRow}>
                  <dt>Started</dt>
                  <dd>{new Date(attempts[0]?.occurred_at ?? latest.occurred_at).toLocaleString()}</dd>
                </div>
                <div className={inspectorStyles.fieldRow}>
                  <dt>Last update</dt>
                  <dd>{new Date(latest.occurred_at).toLocaleString()}</dd>
                </div>
                <div className={inspectorStyles.fieldRow}>
                  <dt>Attempt</dt>
                  <dd>{executionIds.indexOf(activeExecutionId ?? "") + 1} of {executionIds.length || 1}</dd>
                </div>
              </dl>
              <ImplementationDetails event={latest} />
            </>
          ) : (
            <p className="text-small">This stage has not run yet in this session.</p>
          )}
        </Tabs.Content>

        <Tabs.Content value="input" className={styles.tabContent}>
          {activeAttempts.filter((event) => INPUT_EVENT_TYPES.has(event.event_type)).length === 0 ? (
            <p className="text-small">No recorded input for this attempt.</p>
          ) : (
            activeAttempts.filter((event) => INPUT_EVENT_TYPES.has(event.event_type)).map((event) => (
              <div key={event.event_id}>
                <p>{event.plain_summary}</p>
                {event.artifact_ids.map((artifactId) => <ArtifactView key={artifactId} artifactId={artifactId} />)}
              </div>
            ))
          )}
        </Tabs.Content>

        <Tabs.Content value="output" className={styles.tabContent}>
          {activeAttempts.filter((event) => !INPUT_EVENT_TYPES.has(event.event_type)).length === 0 ? (
            <p className="text-small">No recorded output for this attempt.</p>
          ) : (
            activeAttempts.filter((event) => !INPUT_EVENT_TYPES.has(event.event_type)).map((event) => (
              <div key={event.event_id}>
                <p>{event.plain_summary}</p>
                {event.artifact_ids.map((artifactId) => <ArtifactView key={artifactId} artifactId={artifactId} />)}
              </div>
            ))
          )}
        </Tabs.Content>

        <Tabs.Content value="history" className={styles.tabContent}>
          {executionIds.length === 0 ? (
            <p className="text-small">No execution attempts yet.</p>
          ) : (
            <ol className={inspectorStyles.historyList}>
              {executionIds.map((executionId, index) => {
                const executionEvents = attempts.filter((event) => event.execution_id === executionId);
                const executionLatest = executionEvents.at(-1);
                if (!executionLatest) return null;
                const rowStyle = STATUS_STYLES[executionLatest.status];
                return (
                  <li key={executionId}>
                    <button
                      type="button"
                      className={inspectorStyles.historyRow}
                      data-active={executionId === activeExecutionId || undefined}
                      onClick={() => setSelectedExecutionId(executionId)}
                    >
                      <span>Attempt {index + 1}</span>
                      <span style={{ color: `var(${rowStyle.colorVar})` }}>{rowStyle.label}</span>
                      <span className="text-small">{new Date(executionLatest.occurred_at).toLocaleTimeString()}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          )}
        </Tabs.Content>
      </Tabs.Root>
    </motion.div>
  );
}

interface StageFocusPresenceProps {
  componentId: ComponentId | null;
  events: RunEvent[];
  onClose: () => void;
  focusExecutionId?: string | null;
}

export function StageFocusPresence({ componentId, events, onClose, focusExecutionId }: StageFocusPresenceProps) {
  return (
    <AnimatePresence>
      {componentId && <StageFocusPanel componentId={componentId} events={events} onClose={onClose} focusExecutionId={focusExecutionId} key={componentId} />}
    </AnimatePresence>
  );
}
