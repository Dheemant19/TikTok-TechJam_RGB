import { asArray, asRecord, field } from "../api/json";
import type { JsonRecord, RunEventDTO } from "../api/types";
import { NODES } from "../data/nodeRegistry";
import { uiNodeIdForEvent } from "./eventMapping";

function numberField(record: JsonRecord | undefined, key: string): number | null {
  const value = field(record, key);
  return typeof value === "number" ? value : null;
}

function stringField(record: JsonRecord | undefined, key: string): string | null {
  const value = field(record, key);
  return typeof value === "string" ? value : null;
}

export interface BenchmarkSelection {
  id: string;
  label: string;
}

export function selectBenchmark(events: RunEventDTO[]): BenchmarkSelection | null {
  const event = [...events]
    .sort((left, right) => right.sequence - left.sequence)
    .find((item) => item.component_id === "train_data" && item.event_type === "data_ready");
  if (!event) return null;
  const payload = asRecord(event.payload);
  const id = stringField(payload, "benchmark");
  if (!id) return null;
  const label = stringField(payload, "dataset")
    ?? (id === "kuairand_1k" ? "KuaiRand-1K" : "KuaiRand-Pure");
  return { id, label };
}

const TRUST_TIER_LABEL: Record<string, string> = { curated: "Curated bank", discovered: "Hugging Face" };

/** Papers ingested via search_evidence() carry a trust_tier of either
 * "curated" (the seed bank) or "discovered" (currently only ever populated
 * by the Hugging Face Papers provider; see RetrievalService.search_evidence).
 * GitHub is not itself a retrieval source for a citation -- it is per-paper
 * code metadata attached during ingestion -- so it is reported as a separate
 * annotation, not a trust_tier value. */
function paperProvenance(paper: JsonRecord | undefined): { tierLabel: string; hasGithubCode: boolean; githubUrl: string | null } {
  const tier = stringField(paper, "trust_tier");
  const code = asArray(field(paper, "code")) ?? [];
  const firstRepository = code.length > 0 ? asRecord(code[0]) : undefined;
  return {
    tierLabel: tier ? TRUST_TIER_LABEL[tier] ?? tier : "Unknown",
    hasGithubCode: code.length > 0,
    githubUrl: stringField(firstRepository, "repository_url"),
  };
}

export interface ExperimentRow {
  id: string;
  runId: string;
  label: string;
  gauc: number | null;
  ndcg5: number | null;
  primary: number | null;
  status: "baseline" | "accepted" | "rejected" | "ambiguous" | "failed" | "running";
  evidenceSource: string | null;
}

/** Summarizes where a research() cycle's cited evidence came from -- the set
 * of trust tiers among its supporting/contradicting papers (Curated bank vs
 * Hugging Face), plus whether any of them carry an attached GitHub implementation. */
function evidenceSourceSummary(payload: JsonRecord | undefined): string {
  const tiers = new Set<string>();
  let hasGithubCode = false;
  for (const kind of ["supporting", "contradicting"] as const) {
    for (const raw of asArray(field(payload, kind)) ?? []) {
      const { tierLabel, hasGithubCode: itemHasCode } = paperProvenance(asRecord(field(asRecord(raw), "paper")));
      tiers.add(tierLabel);
      hasGithubCode = hasGithubCode || itemHasCode;
    }
  }
  if (tiers.size === 0) return "No evidence cited";
  const label = [...tiers].sort().join(" + ");
  return hasGithubCode ? `${label} (+ GitHub code)` : label;
}

const DECISION_STATUS: Record<string, ExperimentRow["status"]> = {
  retain: "accepted",
  reject: "rejected",
  ambiguous: "ambiguous",
};

/** Builds one row for every bounded experiment attempt, not merely for the
 * attempts that survived smoke checks and reached a watchdog decision. The
 * experiment budget is consumed when a contract is selected because research,
 * patch generation and proxy execution all spend resources. Hiding inert
 * patches made a correct "budget reached (10)" event appear next to only two
 * experiments in the UI.
 *
 * Older ledger events associated the scientist plan with the preceding run ID,
 * so plans are paired in sequence with the next coder-start event. New events
 * include planned_run_id and use that directly. */
export function selectExperiments(events: RunEventDTO[]): ExperimentRow[] {
  const rows: ExperimentRow[] = [];
  const ordered = [...events].sort((left, right) => left.sequence - right.sequence);
  const baselineEvent = ordered.find((event) => event.component_id === "ledger" && event.event_type === "frontier");
  if (baselineEvent) {
    const baselineResult = asRecord(field(asRecord(baselineEvent.payload), "baseline_result"));
    const seeds = asArray(field(baselineResult, "seeds")) ?? [];
    const seedMetrics = seeds.map((seed) => asRecord(field(asRecord(seed), "metrics"))).filter((value): value is JsonRecord => value !== undefined);
    const average = (key: string): number | null => {
      const values = seedMetrics.map((metric) => numberField(metric, key)).filter((value): value is number => value !== null);
      return values.length > 0 ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    };
    rows.push({
      id: "B0",
      runId: "B0",
      label: `Official FM Baseline (${seedMetrics.length} seed${seedMetrics.length === 1 ? "" : "s"})`,
      gauc: average("gauc"),
      ndcg5: average("ndcg_at_5"),
      primary: average("primary"),
      status: "baseline",
      evidenceSource: null,
    });
  }

  const metricByRun = new Map<string, { gauc: number | null; ndcg5: number | null; primary: number | null }>();
  const decisionByRun = new Map<string, ExperimentRow["status"]>();
  const failedRuns = new Set<string>();
  for (const event of ordered) {
    if (event.component_id === "evaluator" && event.event_type === "metric") {
      const metrics = asRecord(field(asRecord(event.payload), "metrics"));
      metricByRun.set(event.run_id, {
        gauc: numberField(metrics, "GAUC"),
        ndcg5: numberField(metrics, "nDCG@5"),
        primary: numberField(metrics, "primary"),
      });
    }
    if (event.component_id === "watchdog" && event.event_type === "frontier") {
      const decision = stringField(asRecord(event.payload), "decision") ?? "";
      const status = DECISION_STATUS[decision];
      if (status) decisionByRun.set(event.run_id, status);
    }
    if (
      event.event_type === "inert_patch"
      || (
        event.status === "failed"
        && ["scientist", "coder", "trainer", "evaluator", "phase_guard"].includes(event.component_id)
      )
    ) {
      failedRuns.add(event.run_id);
    }
  }

  const plans = ordered.filter((event) => event.component_id === "scientist" && event.event_type === "plan");
  const coderStarts = ordered.filter((event) => event.component_id === "coder" && event.event_type === "started");
  const evidenceEvents = ordered.filter((event) => event.component_id === "knowledge_mcp" && event.event_type === "completed");
  plans.forEach((plan, index) => {
    const payload = asRecord(plan.payload);
    const contract = asRecord(field(payload, "contract"));
    const plannedRunId = stringField(payload, "planned_run_id") ?? coderStarts[index]?.run_id ?? plan.run_id;
    const experimentId = stringField(contract, "experiment_id") ?? plannedRunId;
    const metrics = metricByRun.get(plannedRunId);
    const evidence = [...evidenceEvents].reverse().find((event) => event.sequence < plan.sequence);
    rows.push({
      id: experimentId,
      runId: plannedRunId,
      label: experimentId,
      gauc: metrics?.gauc ?? null,
      ndcg5: metrics?.ndcg5 ?? null,
      primary: metrics?.primary ?? null,
      status: decisionByRun.get(plannedRunId) ?? (failedRuns.has(plannedRunId) ? "failed" : "running"),
      evidenceSource: evidence ? evidenceSourceSummary(asRecord(evidence.payload)) : null,
    });
  });

  // A failed Research Agent call consumes one bounded attempt even though it
  // cannot produce an ExperimentContract or start the coder.
  const researchFailures = ordered.filter((event) => event.component_id === "scientist" && event.event_type === "failed");
  researchFailures.forEach((event, index) => {
    rows.push({
      id: `${event.run_id}-research-failure-${index + 1}`,
      runId: event.run_id,
      label: `Research attempt failed (${event.run_id})`,
      gauc: null,
      ndcg5: null,
      primary: null,
      status: "failed",
      evidenceSource: null,
    });
  });
  return rows;
}

export interface ResearchEvidenceCard {
  id: string;
  title: string;
  relevanceNotes: string;
  sourceMode: string;
  trustTierLabel: string;
  hasGithubCode: boolean;
  githubUrl: string | null;
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
        const { tierLabel, hasGithubCode, githubUrl } = paperProvenance(paper);
        cards.push({
          id: paperId,
          title: stringField(paper, "title") ?? paperId,
          relevanceNotes: stringField(paper, "relevance_notes") ?? "",
          sourceMode,
          trustTierLabel: tierLabel,
          hasGithubCode,
          githubUrl,
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
  gpuHours: number | null;
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
 * separate frontend accounting scheme.
 *
 * `gpuHours` stays null until at least one receipt carries a measured value,
 * so an unobservable GPU reads as "not measured" instead of as zero usage.
 * `manualInterventions` is authoritative from the session snapshot; the
 * frontend no longer adds its own per-control-event tally on top, which
 * double-counted every pause/resume/cancel. */
export function selectResources(events: RunEventDTO[]): ResourceSummary {
  const totals: ResourceSummary = { wallSeconds: 0, gpuHours: null, peakRssMb: 0, peakGpuMemoryMb: null, bedrockInputTokens: 0, bedrockOutputTokens: 0, retries: 0, manualInterventions: 0 };
  for (const event of events) {
    if (event.component_id === "trainer" && event.event_type === "usage") {
      const resources = asRecord(field(asRecord(event.payload), "resources"));
      totals.wallSeconds += numberField(resources, "wall_seconds") ?? 0;
      totals.peakRssMb = Math.max(totals.peakRssMb, numberField(resources, "peak_rss_mb") ?? 0);
      const gpu = numberField(resources, "peak_gpu_memory_mb");
      if (gpu !== null) totals.peakGpuMemoryMb = Math.max(totals.peakGpuMemoryMb ?? 0, gpu);
      const gpuHours = numberField(resources, "gpu_hours");
      if (gpuHours !== null) totals.gpuHours = (totals.gpuHours ?? 0) + gpuHours;
      totals.bedrockInputTokens = numberField(resources, "bedrock_input_tokens") ?? totals.bedrockInputTokens;
      totals.bedrockOutputTokens = numberField(resources, "bedrock_output_tokens") ?? totals.bedrockOutputTokens;
      totals.retries = numberField(resources, "retries") ?? totals.retries;
      totals.manualInterventions = numberField(resources, "manual_interventions") ?? totals.manualInterventions;
    }
  }
  return totals;
}

export interface TimelineRow {
  sequence: number;
  occurredAt: string;
  componentLabel: string;
  action: string;
  method: string | null;
  status: string;
}

/** The Autonomy Log is the same ordered ledger the Live Workflow view
 * animates in real time (Plan_UI.md #5.2), so it reads directly off the
 * event stream instead of a separate static log. Every row's stage label
 * must resolve through `uiNodeIdForEvent` -- the same routing the cards
 * themselves use -- not the raw `component_id`. Several backend components
 * multiplex more than one presentation card (`trainer` covers Tier 1-4 plus
 * baseline reproduction; `phase_guard` covers the baseline safety gate plus
 * a proxy-stage rejection), so labeling directly off `component_id` showed
 * "Train the Model" for baseline events and "Check Data Safety" for a
 * proxy-only rejection -- both belonging to a different card entirely. */
export function selectAutonomyTimeline(events: RunEventDTO[]): TimelineRow[] {
  return [...events]
    .sort((a, b) => b.sequence - a.sequence)
    .map((event) => {
      const payload = asRecord(event.payload);
      const contract = asRecord(field(payload, "contract"));
      const training = asRecord(field(payload, "training"));
      const methodFamily = stringField(contract, "method_family") ?? stringField(training, "model_family");
      const iterationStrategy = stringField(contract, "iteration_strategy");
      const runtimeDevice = stringField(training, "device_name") ?? stringField(training, "device");
      const decisionRationale = stringField(contract, "decision_rationale");
      const action = event.component_id === "scientist"
        && event.event_type === "plan"
        && methodFamily
        ? `${decisionRationale ?? "Selected from prior run evidence"} Change: ${stringField(contract, "primary_change") ?? event.plain_summary}`
        : event.plain_summary;
      return {
        sequence: event.sequence,
        occurredAt: event.occurred_at,
        componentLabel: event.component_id === "orchestrator"
          ? "Workflow Orchestrator"
          : NODES.find((node) => node.id === uiNodeIdForEvent(event))?.label ?? event.component_id,
        action,
        method: methodFamily
          ? `${methodFamily}${iterationStrategy || runtimeDevice ? ` · ${iterationStrategy?.split("_").join(" ") ?? runtimeDevice}` : ""}`
          : null,
        status: event.status,
      };
    });
}

/** The stage-detail "Continue to" control must be branch-aware: after a
 * rejected watchdog decision the real next LangGraph step is another
 * research cycle, not the ledger/package tail of the run (AGENTS.md #5). */
export function selectLatestWatchdogDecision(events: RunEventDTO[]): string | null {
  const ordered = [...events].sort((left, right) => left.sequence - right.sequence);
  for (let i = ordered.length - 1; i >= 0; i--) {
    const event = ordered[i];
    if (event.component_id !== "watchdog" || event.event_type !== "frontier") continue;
    return stringField(asRecord(event.payload), "decision");
  }
  return null;
}
