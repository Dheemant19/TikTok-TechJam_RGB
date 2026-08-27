import { useMemo } from "react";
import type { RunEvent } from "@/api/types";
import { BarChart } from "@/charts/BarChart";
import styles from "./Routes.module.css";

interface ResourcesProps {
  events: RunEvent[];
}

interface ResourceTotals {
  wall_seconds: number;
  peak_rss_mb: number;
  peak_gpu_memory_mb: number;
  bedrock_input_tokens: number;
  bedrock_output_tokens: number;
  retries: number;
  manual_interventions: number;
}

function payloadField<T>(payload: Record<string, unknown>, key: string): T | null {
  return key in payload ? (payload[key] as T) : null;
}

function sum(values: number[]): number {
  return values.reduce((total, value) => total + value, 0);
}

export function Resources({ events }: ResourcesProps) {
  const perRun = useMemo(() => {
    return events
      .filter((event) => event.component_id === "trainer" && event.event_type === "usage")
      .map((event) => ({ runId: event.run_id, totals: payloadField<ResourceTotals>(event.payload, "resources") }))
      .filter((row): row is { runId: string; totals: ResourceTotals } => row.totals !== null);
  }, [events]);

  const cumulative = useMemo<ResourceTotals>(() => {
    return {
      wall_seconds: sum(perRun.map((row) => row.totals.wall_seconds)),
      peak_rss_mb: Math.max(0, ...perRun.map((row) => row.totals.peak_rss_mb)),
      peak_gpu_memory_mb: Math.max(0, ...perRun.map((row) => row.totals.peak_gpu_memory_mb)),
      bedrock_input_tokens: sum(perRun.map((row) => row.totals.bedrock_input_tokens)),
      bedrock_output_tokens: sum(perRun.map((row) => row.totals.bedrock_output_tokens)),
      retries: sum(perRun.map((row) => row.totals.retries)),
      manual_interventions: sum(perRun.map((row) => row.totals.manual_interventions)),
    };
  }, [perRun]);

  function formatHours(seconds: number): string {
    return (seconds / 3600).toFixed(3);
  }

  return (
    <div className={styles.page}>
      <h1>Resources</h1>
      <p className="text-small">Cumulative and per-run compute and LLM usage. Manual interventions count human edits, restarts, or overrides.</p>

      <section className={styles.card}>
        <h2>Cumulative for this session</h2>
        <dl className={styles.statGrid}>
          <dt>Wall time</dt>
          <dd>{formatHours(cumulative.wall_seconds)} h</dd>
          <dt>Peak memory observed</dt>
          <dd>
            {cumulative.peak_rss_mb.toFixed(0)} MB RSS
            {cumulative.peak_gpu_memory_mb > 0 ? `, ${cumulative.peak_gpu_memory_mb.toFixed(0)} MB GPU` : " — no GPU device detected"}
          </dd>
          <dt>Bedrock input tokens</dt>
          <dd>{cumulative.bedrock_input_tokens.toLocaleString()}</dd>
          <dt>Bedrock output tokens</dt>
          <dd>{cumulative.bedrock_output_tokens.toLocaleString()}</dd>
          <dt>Recovery retries</dt>
          <dd>{cumulative.retries}</dd>
          <dt>Manual interventions</dt>
          <dd>{cumulative.manual_interventions}</dd>
        </dl>
      </section>

      {perRun.length > 0 && (
        <BarChart
          title="Bedrock tokens by run"
          xAxisLabel="Run"
          yAxisLabel="Tokens"
          categories={perRun.map((row) => row.runId)}
          series={[
            { name: "Input tokens", values: perRun.map((row) => row.totals.bedrock_input_tokens) },
            { name: "Output tokens", values: perRun.map((row) => row.totals.bedrock_output_tokens) },
          ]}
        />
      )}

      {perRun.length > 0 && (
        <BarChart
          title="Wall time by run"
          xAxisLabel="Run"
          yAxisLabel="Seconds"
          categories={perRun.map((row) => row.runId)}
          series={[{ name: "Wall seconds", values: perRun.map((row) => row.totals.wall_seconds) }]}
        />
      )}

      {perRun.length === 0 && <p className="text-small">No resource usage has been recorded yet in this session.</p>}
    </div>
  );
}
