// Interface demo data -- redacted, illustrative shapes derived from the ledger event
// contract in AGENTS.md / Plan_Workflow.md. Not a completed experiment result.
// Per-node live state (status, elapsed time, summary/input/output/history) lives in
// liveworkflow/runStore.ts and liveworkflow/laneData.ts instead of here.

export const DEMO_TIMELINE = [
  { t: "T+00:55", component: "coder", action: "Applied code diff", outcome: "Ready for smoke test", duration: "Not recorded" },
  { t: "T+00:52", component: "pruner", action: "Ran fast safety tests", outcome: "Passed", duration: "3s" },
  { t: "T+00:41", component: "coder", action: "Wrote code change", outcome: "1 file, 61 lines", duration: "11s" },
  { t: "T+00:33", component: "scientist", action: "Selected next experiment", outcome: "BPR pairwise loss", duration: "8s" },
  { t: "T+00:21", component: "knowledge_mcp", action: "Retrieved research evidence", outcome: "5 documents", duration: "12s" },
  { t: "T+00:19", component: "phase_guard", action: "Checked data safety", outcome: "12/12 checks passed", duration: "2s" },
  { t: "T+00:04", component: "data_profiler", action: "Inspected & prepared data", outcome: "Transform frozen", duration: "15s" },
  { t: "T+00:00", component: "train_data", action: "Loaded training data", outcome: "1.14M rows", duration: "4s" },
];

export const DEMO_EXPERIMENTS = [
  { id: "official-fm", label: "Official FM Baseline", gauc: 0.661, ndcg5: 0.5282, primary: 0.5946, status: "baseline" as const },
  { id: "exp-001", label: "exp-001: +CWM static features", gauc: 0.6598, ndcg5: 0.528, primary: 0.594, status: "rejected" as const },
  { id: "exp-002", label: "exp-002: capacity sweep k=16", gauc: 0.6602, ndcg5: 0.5273, primary: 0.5938, status: "rejected" as const },
  { id: "exp-003", label: "exp-003: BPR pairwise loss", gauc: null, ndcg5: null, primary: null, status: "running" as const },
];

export const DEMO_RESOURCES = {
  llmInputTokens: 812_400,
  llmOutputTokens: 96_120,
  gpuHours: 3.4,
  wallClockSeconds: 6_655,
  manualInterventions: 0,
};

export const DEMO_RESEARCH = [
  {
    id: "bpr-2009",
    title: "BPR: Bayesian Personalized Ranking from Implicit Feedback",
    year: 2009,
    tags: ["ranking_loss", "pairwise"],
    note: "Motivates replacing pointwise BCE with a pairwise objective aligned to GAUC.",
  },
  {
    id: "sasrec-2018",
    title: "Self-Attentive Sequential Recommendation",
    year: 2018,
    tags: ["sequence_modeling"],
    note: "Candidate for modeling chronological interaction history per user.",
  },
  {
    id: "ple-2020",
    title: "Progressive Layered Extraction (PLE) for Multi-Task Learning",
    year: 2020,
    tags: ["multi_task"],
    note: "Candidate for gating auxiliary signals (is_click, is_like) against long_view.",
  },
];
