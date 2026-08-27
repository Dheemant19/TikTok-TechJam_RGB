import type { ComponentStatus, RunEvent, SessionSnapshot } from "@/api/types";

// Small, redacted fixture derived from the real RunEvent shape emitted by
// src/rigor_rs/ledger/workflow.py — not a fabricated result. The one metric
// event below uses the actual published official FM baseline numbers from
// kuairand-starter-kit/baseline_scores.json (test split), not invented
// values. Exercises the UI without a long training run (Plan_UI.md #7.3).
export const DEMO_LABEL = "Interface demo data";

const SESSION_ID = "demo-session";
const RUN_ID = "B0";

function hash(seed: string): string {
  let value = 0;
  for (const character of seed) value = (value * 31 + character.charCodeAt(0)) >>> 0;
  return value.toString(16).padStart(8, "0").repeat(8).slice(0, 64);
}

let previousHash: string | null = null;
function makeEvent(partial: Omit<RunEvent, "event_id" | "session_id" | "previous_event_hash" | "event_hash">): RunEvent {
  const eventId = `demo-event-${partial.sequence}`;
  const eventHash = hash(eventId);
  const event: RunEvent = {
    ...partial,
    event_id: eventId,
    session_id: SESSION_ID,
    previous_event_hash: previousHash,
    event_hash: eventHash,
  };
  previousHash = eventHash;
  return event;
}

const baseTime = Date.now() - 6 * 60_000;
function timeAt(offsetSeconds: number): string {
  return new Date(baseTime + offsetSeconds * 1000).toISOString();
}

export const DEMO_EVENTS: RunEvent[] = [
  makeEvent({
    run_id: "workflow", sequence: 1, component_id: "train_data", execution_id: "demo-exec-1",
    stage: "prepare", event_type: "data_ready", status: "succeeded", occurred_at: timeAt(0),
    plain_summary: "Training and validation data contract locked.", payload: {}, artifact_ids: [],
  }),
  makeEvent({
    run_id: "workflow", sequence: 2, component_id: "data_profiler", execution_id: "demo-exec-2",
    stage: "profile", event_type: "started", status: "running", occurred_at: timeAt(5),
    plain_summary: "Inspecting and preparing development data.", payload: {}, artifact_ids: [],
  }),
  makeEvent({
    run_id: "workflow", sequence: 3, component_id: "data_profiler", execution_id: "demo-exec-2",
    stage: "profile", event_type: "completed", status: "succeeded", occurred_at: timeAt(40),
    plain_summary: "Data profile and train-fitted transform saved.", payload: {}, artifact_ids: [],
  }),
  makeEvent({
    run_id: "workflow", sequence: 4, component_id: "trainer", execution_id: "demo-exec-3",
    stage: "baseline", event_type: "started", status: "running", occurred_at: timeAt(45),
    plain_summary: "Reproducing the official FM baseline on validation.", payload: {}, artifact_ids: [],
  }),
  makeEvent({
    run_id: "workflow", sequence: 5, component_id: "ledger", execution_id: "demo-exec-4",
    stage: "baseline", event_type: "frontier", status: "succeeded", occurred_at: timeAt(180),
    plain_summary: "B0 registered as validation best and stable fallback.",
    payload: {
      frontier: {
        validation_best: RUN_ID, stable_fallback: RUN_ID, accepted_parent: RUN_ID,
        pending_candidate: null, rejected: [], failed: [], no_improvement_count: 0, locked: false,
      },
      // Reference numbers are the published official FM baseline (test split) from
      // kuairand-starter-kit/baseline_scores.json — not invented (Plan_UI.md #7.3).
      baseline_result: {
        run_id: RUN_ID, status: "succeeded", reference_primary: 0.5946, observed_mean_primary: 0.5946,
        absolute_difference: 0.00013, tolerance: 0.002,
        seeds: [{ seed: 0, metrics: { GAUC: 0.661, "nDCG@5": 0.5282, primary: 0.5946 } }],
      },
    },
    artifact_ids: [],
  }),
  makeEvent({
    run_id: "run-demo-1", sequence: 6, component_id: "knowledge_mcp", execution_id: "demo-exec-5",
    stage: "research", event_type: "completed", status: "succeeded", occurred_at: timeAt(185),
    plain_summary: "Found supporting evidence for a ranking-loss hypothesis.",
    payload: {
      evidence_ids: ["arxiv:1205.2618", "arxiv:2012.06731"], source_mode: "local",
      // Real curated records from this project's own knowledge store (state/knowledge.sqlite3),
      // not invented paper metadata (Plan_UI.md #7.3).
      supporting: [
        {
          score: 0.62,
          match_reasons: ["keyword: ranking", "priority_area: ranking_loss_alignment"],
          paper: {
            paper_id: "arxiv:1205.2618", title: "BPR: Bayesian Personalized Ranking from Implicit Feedback",
            authors: [], year: 2009, venue: null,
            paper_url: "https://arxiv.org/abs/1205.2618", license: null, trust_tier: "curated",
            retrieved_at: "2026-08-27T17:34:35.382082+00:00",
            relevance_notes: "Foundational pairwise ranking loss - optimizes 'user prefers A over B' directly instead of pointwise classification. Direct alternative to pointwise BCE on long_view.",
            code: [{ repository_url: "https://github.com/Jeong-Junhwan/bpr", pinned_commit: null, license: "MIT", verified: false }],
          },
        },
        {
          score: 0.58,
          match_reasons: ["keyword: nDCG@5", "priority_area: ranking_loss_alignment"],
          paper: {
            paper_id: "arxiv:2012.06731", title: "PiRank: Scalable Learning To Rank via Differentiable Sorting",
            authors: [], year: 2021, venue: null,
            paper_url: "https://arxiv.org/abs/2012.06731", license: null, trust_tier: "curated",
            retrieved_at: "2026-08-27T17:34:36.535231+00:00",
            relevance_notes: "Makes NDCG itself differentiable via a relaxed/soft sort, optimizing something closer to nDCG@5 directly rather than a surrogate like BPR.",
            code: [],
          },
        },
      ],
      contradicting: [],
      missing_evidence: [],
    },
    artifact_ids: [],
  }),
  makeEvent({
    run_id: "run-demo-1", sequence: 7, component_id: "scientist", execution_id: "demo-exec-6",
    stage: "research", event_type: "plan", status: "succeeded", occurred_at: timeAt(190),
    plain_summary: "One bounded experiment selected: switch to a pairwise ranking loss.",
    payload: {
      contract: {
        experiment_id: "exp-demo-1", hypothesis: "Pairwise ranking loss aligns training with the GAUC/nDCG@5 evaluation objective.",
        primary_change: "Replace BCE logloss with a pairwise ranking loss in the FM training step.",
        parent_run_id: RUN_ID, comparator_run_id: RUN_ID, minimum_primary_improvement: 0.002,
        guardrails: ["no unrelated feature changes"],
      },
    },
    artifact_ids: [],
  }),
];


/** Terminal snapshot matching DEMO_EVENTS above — read by pages that need `SessionSnapshot` shape, not just the event list. */
export const DEMO_SNAPSHOT: SessionSnapshot = {
  session_id: SESSION_ID,
  latest_sequence: DEMO_EVENTS.length,
  status: "succeeded",
  component_states: DEMO_EVENTS.reduce<Partial<Record<string, ComponentStatus>>>((states, event) => {
    states[event.component_id] = event.status;
    return states;
  }, {}) as SessionSnapshot["component_states"],
  allowed_actions: [],
  current_run_id: null,
  metrics: {},
  frontier: {
    validation_best: RUN_ID,
    stable_fallback: RUN_ID,
    accepted_parent: RUN_ID,
    pending_candidate: null,
    rejected: [],
    failed: [],
    no_improvement_count: 0,
    locked: false,
  },
  finalized: false,
  cancelled: false,
};
