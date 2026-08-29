import { asArray, asRecord, field } from "../api/json";
import type { JsonRecord, JsonValue } from "../api/types";
import { REDACTED_LABEL } from "../api/types";
import type { NodeDef } from "../data/nodeRegistry";
import { statusMeta } from "./NodeCard";
import type { Fact, FieldRow, HistoryRow, NodeDetail } from "./laneData";
import type { NodeRuntimeState } from "./eventMapping";

function formatTime(iso: string | null): string {
  if (!iso) return "Not recorded";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function historyFrom(state: NodeRuntimeState): HistoryRow[] {
  if (state.events.length === 0) {
    return [{ attempt: 0, status: "Waiting", time: "Not recorded", note: "Not started yet this run", dotColor: statusMeta("waiting").dot }];
  }
  return state.events.map((event, index) => ({
    attempt: index + 1,
    status: statusMeta(event.status).text,
    time: formatTime(event.occurred_at),
    note: event.plain_summary,
    dotColor: statusMeta(event.status).dot,
  }));
}

function scalarText(value: JsonValue | undefined, fallback = "Not yet available"): string {
  if (value === undefined || value === null) return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(4);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return fallback;
}

function latestPayload(state: NodeRuntimeState): JsonRecord | undefined {
  const last = state.events[state.events.length - 1];
  return last ? asRecord(last.payload) : undefined;
}

function metricsFacts(metrics: JsonRecord | undefined): Fact[] {
  if (!metrics) return [];
  return [
    { label: "GAUC", value: scalarText(field(metrics, "GAUC")) },
    { label: "nDCG@5", value: scalarText(field(metrics, "nDCG@5")) },
    { label: "Primary score", value: scalarText(field(metrics, "primary")) },
  ];
}

const BUILDERS: Record<string, (state: NodeRuntimeState) => Partial<NodeDetail>> = {
  train_data: (state) => ({
    output: [{ label: "Status", value: state.events.length ? "Split contract locked for this session" : "Waiting for session start" }],
  }),
  data_profiler: (state) => {
    const payload = latestPayload(state);
    const profileReceipt = asRecord(field(payload, "profile"));
    const transform = asRecord(field(payload, "transform"));
    const receipt = asRecord(field(transform, "receipt"));
    const receiptArtifact = asRecord(field(receipt, "receipt"));
    const receiptHash = scalarText(field(receiptArtifact, "content_hash")).slice(0, 16);
    return {
      facts: [
        { label: "Cache hit", value: scalarText(field(profileReceipt, "cache_hit")) },
        { label: "Transform receipt hash", value: receiptHash },
      ],
      output: payload
        ? [
            { label: "profile.json", value: "Open the Data Profile page for full diagnostics" },
            { label: "transform_receipt.json", value: receiptHash, mono: true },
          ]
        : [{ label: "profile.json", value: "Not yet produced" }],
    };
  },
  phase_guard: (state) => {
    const halt = state.events.find((event) => event.component_id === "phase_guard");
    return {
      facts: [{ label: "Result", value: halt ? "Integrity halt triggered" : state.status === "succeeded" ? "All checks passed" : "Not yet evaluated" }],
      output: halt ? [{ label: "Reason", value: halt.plain_summary }] : [{ label: "Decision", value: state.status === "succeeded" ? "Approved to continue" : "Pending" }],
    };
  },
  knowledge_mcp: (state) => {
    const payload = latestPayload(state);
    const supporting = asArray(field(payload, "supporting")) ?? [];
    const contradicting = asArray(field(payload, "contradicting")) ?? [];
    const sourceMode = scalarText(field(payload, "source_mode"));
    return {
      facts: [
        { label: "Supporting evidence", value: String(supporting.length) },
        { label: "Contradicting evidence", value: String(contradicting.length) },
        { label: "Source", value: sourceMode },
      ],
      output: [{ label: "Evidence cards", value: `${supporting.length + contradicting.length} with citations and retrieval time` }],
    };
  },
  scientist: (state) => {
    const payload = latestPayload(state);
    const contract = asRecord(field(payload, "contract"));
    return {
      facts: [
        { label: "Hypothesis", value: scalarText(field(contract, "hypothesis")) },
        { label: "Predicted GAUC", value: scalarText(field(contract, "predicted_gauc_direction")) },
        { label: "Predicted nDCG@5", value: scalarText(field(contract, "predicted_ndcg_at_5_direction")) },
      ],
      output: [{ label: "Primary change", value: scalarText(field(contract, "primary_change")) }],
    };
  },
  coder: (state) => {
    const payload = latestPayload(state);
    const files = asArray(field(payload, "files")) ?? [];
    return {
      facts: [
        { label: "Files changed", value: String(files.length) },
        { label: "Patch hash", value: scalarText(field(payload, "patch_hash"))?.slice(0, 16) ?? "Not yet available" },
      ],
      output: [{ label: "Patch", value: files.map((name) => scalarText(name)).join(", ") || "Not yet available" }],
    };
  },
  pruner: (state) => {
    const receipt = asRecord(field(latestPayload(state), "receipt"));
    const succeeded = field(receipt, "status") === "succeeded";
    return {
      facts: [
        { label: "Status", value: scalarText(field(receipt, "status")) },
        { label: "Duration", value: scalarText(field(receipt, "wall_seconds")) + "s" },
      ],
      output: [
        {
          label: "Result",
          value: succeeded
            ? "All fast tests passed"
            : scalarText(field(receipt, "error"), "Failed with no captured output") || "Failed with no captured output",
        },
      ],
    };
  },
  trainer: (state) => {
    const receipts = state.events.map((event) => asRecord(field(asRecord(event.payload), "receipt"))).filter((value): value is JsonRecord => value !== undefined);
    const last = receipts[receipts.length - 1];
    const resources = asRecord(field(latestPayload(state), "resources"));
    return {
      facts: [
        { label: "Tiers recorded", value: String(receipts.length) },
        { label: "Peak GPU memory", value: resources ? scalarText(field(resources, "peak_gpu_memory_mb")) + " MB" : "Not yet available" },
        { label: "Wall seconds", value: last ? scalarText(field(last, "wall_seconds")) : "Not yet available" },
      ],
      output: [{ label: "Checkpoint", value: REDACTED_LABEL }],
    };
  },
  recovery: (state) => {
    if (state.events.length === 0) {
      return { facts: [{ label: "Status", value: "On standby" }], output: [{ label: "Restored state", value: "Not activated this run" }] };
    }
    const payload = latestPayload(state);
    return {
      facts: [
        { label: "Category", value: scalarText(field(payload, "category")) },
        { label: "Attempt", value: scalarText(field(payload, "attempt")) },
      ],
      output: [{ label: "Action taken", value: scalarText(field(payload, "action")) }],
    };
  },
  evaluator: (state) => {
    const metrics = asRecord(field(latestPayload(state), "metrics"));
    return { facts: metricsFacts(metrics), output: [{ label: "Metrics", value: metrics ? `GAUC ${scalarText(field(metrics, "GAUC"))} - nDCG@5 ${scalarText(field(metrics, "nDCG@5"))} - primary ${scalarText(field(metrics, "primary"))}` : "Not yet available" }] };
  },
  watchdog: (state) => {
    const payload = latestPayload(state);
    const converged = field(payload, "converged");
    const decision = scalarText(field(payload, "decision"));
    return {
      facts: [
        { label: "Decision", value: decision },
        { label: "Converged", value: scalarText(converged) },
        { label: "Budget stop", value: scalarText(field(payload, "budget_stop")) },
      ],
      output: [{ label: "Decision", value: decision }],
    };
  },
  ledger: (state) => {
    const payload = latestPayload(state);
    const frontier = asRecord(field(payload, "frontier"));
    return {
      facts: [
        { label: "Events this run", value: String(state.events.length) },
        { label: "Validation best", value: scalarText(field(frontier, "validation_best")) },
        { label: "Stable fallback", value: scalarText(field(frontier, "stable_fallback")) },
      ],
      output: [{ label: "Event log", value: `${state.events.length} recorded event(s) for this component` }],
    };
  },
};

export function buildNodeDetail(node: NodeDef, states: Record<string, NodeRuntimeState>, staticDetail: NodeDetail): NodeDetail {
  const state = states[node.id];
  if (!state) return staticDetail;
  const overrides = BUILDERS[node.id]?.(state);
  const history = historyFrom(state);
  if (!overrides) return { ...staticDetail, history };
  return {
    summary: staticDetail.summary,
    facts: overrides.facts && overrides.facts.length > 0 ? overrides.facts : staticDetail.facts,
    input: staticDetail.input,
    output: overrides.output && overrides.output.length > 0 ? overrides.output : staticDetail.output,
    history,
  };
}

export type { FieldRow };
