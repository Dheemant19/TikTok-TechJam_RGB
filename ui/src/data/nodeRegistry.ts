export type Group =
  | "data"
  | "research"
  | "code"
  | "train"
  | "decide";

export interface NodeDef {
  id: string;
  label: string;
  /** Secondary architecture label shown under the plain-language label. */
  archLabel: string;
  group: Group;
  /** Two-letter monogram for the node's badge. */
  mono: string;
  isRecovery?: boolean;
}

export const GROUP_LABELS: Record<Group, string> = {
  data: "Data",
  research: "Research",
  code: "Code & Safety",
  train: "Train & Score",
  decide: "Decide & Package",
};

export const GROUP_ORDER: Group[] = ["data", "research", "code", "train", "decide"];

export const NODES: NodeDef[] = [
  { id: "train_data", label: "Training Data", archLabel: "Dataset", group: "data", mono: "TD" },
  { id: "data_profiler", label: "Inspect & Prepare Data", archLabel: "Data Profiler", group: "data", mono: "DP" },
  { id: "phase_guard", label: "Check Data Safety", archLabel: "Safety Gate", group: "data", mono: "SG" },

  { id: "knowledge_mcp", label: "Find Research Evidence", archLabel: "Research Agent (MCP)", group: "research", mono: "RA" },
  { id: "scientist", label: "Choose the Next Experiment", archLabel: "Experiment Selector", group: "research", mono: "ES" },

  { id: "coder", label: "Write the Code Change", archLabel: "Code Agent", group: "code", mono: "CA" },
  { id: "pruner", label: "Run Fast Safety Tests", archLabel: "Fast Test Suite", group: "code", mono: "FT" },

  { id: "trainer", label: "Train the Model", archLabel: "Training Job", group: "train", mono: "TR" },
  { id: "recovery", label: "Recover from Failures", archLabel: "Recovery Agent", group: "train", mono: "RC", isRecovery: true },
  { id: "evaluator", label: "Score on Validation", archLabel: "Official Evaluator", group: "train", mono: "EV" },

  { id: "watchdog", label: "Decide: Continue or Stop", archLabel: "Autonomy Controller", group: "decide", mono: "WD" },
  { id: "ledger", label: "Save Run Evidence", archLabel: "Event Ledger", group: "decide", mono: "LG" },
  { id: "finalizer", label: "Build Final Package", archLabel: "Package Builder", group: "decide", mono: "FZ" },
  { id: "submission", label: "Verified Predictions", archLabel: "Final Artifact", group: "decide", mono: "SB" },
];

/** The 13-node automatic run order (the standby Recovery node is excluded). */
export const RUN_ORDER = [
  "train_data",
  "data_profiler",
  "phase_guard",
  "knowledge_mcp",
  "scientist",
  "coder",
  "pruner",
  "trainer",
  "evaluator",
  "watchdog",
  "ledger",
  "finalizer",
  "submission",
];

const MAIN_EDGES: [string, string][] = RUN_ORDER.slice(0, -1).map((id, i) => [id, RUN_ORDER[i + 1]]);
export const EDGES: [string, string][] = [...MAIN_EDGES, ["trainer", "recovery"]];

export type NodeStatus =
  | "waiting"
  | "ready"
  | "running"
  | "paused"
  | "succeeded"
  | "failed"
  | "rejected"
  | "skipped"
  | "blocked";
