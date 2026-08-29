import { asArray, asRecord, field } from "../api/json";
import type { JsonRecord, RunEventDTO } from "../api/types";
import { NODES } from "../data/nodeRegistry";

function numberField(record: JsonRecord | undefined, key: string): number | null {
  const value = field(record, key);
  return typeof value === "number" ? value : null;
}

function stringField(record: JsonRecord | undefined, key: string): string | null {
  const value = field(record, key);
  return typeof value === "string" ? value : null;
}

export interface ExperimentRow {
  id: string;
  label: string;
  gauc: number | null;
  ndcg5: number | null;
  primary: number | null;
  status: "baseline" | "accepted" | "rejected" | "ambiguous" | "failed" | "running";
}

const DECISION_STATUS: Record<string, ExperimentRow["status"]> = {
  retain: "accepted",
  reject: "rejected",
  ambiguous: "ambiguous",
};

/** Builds the Experiments page's rows straight from ledger events: the B0
 * baseline registration plus one row per watchdog decision, each compared
 * against the official FM baseline rather than an intermediate best
 * (Plan_UI.md #5.1, AGENTS.md baseline rules). */
export function selectExperiments(events: RunEventDTO[]): ExperimentRow[] {
  const rows: ExperimentRow[] = [];
  const baselineEvent = events.find((event) => event.component_id === "ledger" && event.event_type === "frontier");
  if (baselineEvent) {
    const baselineResult = asRecord(field(asRecord(baselineEvent.payload), "baseline_result"));
    const seeds = asArray(field(baselineResult, "seeds")) ?? [];
    // baseline.py dumps `MetricReceipt.model_dump()` directly for each seed,
    // so the field names are the Pydantic model's own (lowercase `gauc` /
    // `ndcg_at_5`), unlike the evaluator node's own event payload which
    // relabels them to the organizer's display names (`GAUC` / `nDCG@5`).
    const seedMetrics = seeds.map((seed) => asRecord(field(asRecord(seed), "metrics"))).filter((value): value is JsonRecord => value !== undefined);
    const average = (key: string): number | null => {
      const values = seedMetrics.map((metric) => numberField(metric, key)).filter((value): value is number => value !== null);
      return values.length > 0 ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    };
    rows.push({
      id: "B0",
      label: `Official FM Baseline (${seedMetrics.length} seed${seedMetrics.length === 1 ? "" : "s"})`,
      gauc: average("gauc"),
      ndcg5: average("ndcg_at_5"),
      primary: average("primary"),
      status: "baseline",
    });
  }

  const metricByRun = new Map<string, { gauc: number | null; ndcg5: number | null; primary: number | null }>();
  for (const event of events) {
    if (event.component_id !== "evaluator" || event.event_type !== "metric") continue;
    const metrics = asRecord(field(asRecord(event.payload), "metrics"));
    metricByRun.set(event.run_id, { gauc: numberField(metrics, "GAUC"), ndcg5: numberField(metrics, "nDCG@5"), primary: numberField(metrics, "primary") });
  }

  for (const event of events) {
    if (event.component_id !== "watchdog" || event.event_type !== "frontier") continue;
    const payload = asRecord(event.payload);
    const experimentId = stringField(payload, "experiment_id") ?? event.run_id;
    const decision = stringField(payload, "decision") ?? "";
    const metrics = metricByRun.get(event.run_id);
    rows.push({
      id: experimentId,
      label: experimentId,
      gauc: metrics?.gauc ?? null,
      ndcg5: metrics?.ndcg5 ?? null,
      primary: metrics?.primary ?? null,
      status: DECISION_STATUS[decision] ?? "running",
    });
  }
  return rows;
}

export interface ResearchEvidenceCard {
  id: string;
  title: string;
  relevanceNotes: string;
  sourceMode: string;
  kind: "supporting" | "contradicting";
}

/** The Research Library page shows the same evidence cards the Research
 * Agent actually received from the Research Knowledge MCP (Plan_MCP.md #8,
 * Plan_UI.md #5.1), not a static illustration. */
export function selectResearchEvidence(events: RunEventDTO[]): { cards: ResearchEvidenceCard[]; missingEvidence: string[] } {
  const cards: ResearchEvidenceCard[] = [];
  const missingEvidence: string[] = [];
  for (const event of events) {
    if (event.component_id !== "knowledge_mcp" || event.event_type !== "completed") continue;
    const payload = asRecord(event.payload);
    const sourceMode = stringField(payload, "source_mode") ?? "unknown";
    for (const kind of ["supporting", "contradicting"] as const) {
      for (const raw of asArray(field(payload, kind)) ?? []) {
        const item = asRecord(raw);
        const paper = asRecord(field(item, "paper"));
        const paperId = stringField(paper, "paper_id");
        if (!paperId) continue;
        cards.push({
          id: paperId,
          title: stringField(paper, "title") ?? paperId,
          relevanceNotes: stringField(paper, "relevance_notes") ?? "",
          sourceMode,
          kind,
        });
      }
    }
    for (const raw of asArray(field(payload, "missing_evidence")) ?? []) {
      const value = typeof raw === "string" ? raw : null;
      if (value) missingEvidence.push(value);
    }
  }
  return { cards, missingEvidence };
}

export interface ResourceSummary {
  wallSeconds: number;
  peakRssMb: number;
  peakGpuMemoryMb: number | null;
  bedrockInputTokens: number;
  bedrockOutputTokens: number;
  retries: number;
  manualInterventions: number;
}

/** Sums every recorded resource-usage receipt (one per completed experiment
 * run) into the cumulative totals the Resources page shows, matching the
 * `ResourceTotals` contract (contract/models.py) rather than inventing a
 * separate frontend accounting scheme. */
export function selectResources(events: RunEventDTO[]): ResourceSummary {
  const totals: ResourceSummary = { wallSeconds: 0, peakRssMb: 0, peakGpuMemoryMb: null, bedrockInputTokens: 0, bedrockOutputTokens: 0, retries: 0, manualInterventions: 0 };
  for (const event of events) {
    if (event.component_id === "trainer" && event.event_type === "usage") {
      const resources = asRecord(field(asRecord(event.payload), "resources"));
      totals.wallSeconds += numberField(resources, "wall_seconds") ?? 0;
      totals.peakRssMb = Math.max(totals.peakRssMb, numberField(resources, "peak_rss_mb") ?? 0);
      const gpu = numberField(resources, "peak_gpu_memory_mb");
      if (gpu !== null) totals.peakGpuMemoryMb = Math.max(totals.peakGpuMemoryMb ?? 0, gpu);
      totals.bedrockInputTokens = numberField(resources, "bedrock_input_tokens") ?? totals.bedrockInputTokens;
      totals.bedrockOutputTokens = numberField(resources, "bedrock_output_tokens") ?? totals.bedrockOutputTokens;
      totals.retries = numberField(resources, "retries") ?? totals.retries;
      totals.manualInterventions = numberField(resources, "manual_interventions") ?? totals.manualInterventions;
    }
    if (event.event_type.startsWith("control_")) totals.manualInterventions += 1;
  }
  return totals;
}

export interface TimelineRow {
  sequence: number;
  occurredAt: string;
  componentLabel: string;
  action: string;
  status: string;
}

/** The Autonomy Log is the same ordered ledger the Live Workflow view
 * animates in real time (Plan_UI.md #5.2), so it reads directly off the
 * event stream instead of a separate static log. */
export function selectAutonomyTimeline(events: RunEventDTO[]): TimelineRow[] {
  return [...events]
    .sort((a, b) => b.sequence - a.sequence)
    .map((event) => ({
      sequence: event.sequence,
      occurredAt: event.occurred_at,
      componentLabel: NODES.find((node) => node.id === event.component_id)?.label ?? event.component_id,
      action: event.plain_summary,
      status: event.status,
    }));
}
