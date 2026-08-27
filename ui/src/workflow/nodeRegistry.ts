import type { ComponentId } from "@/api/types";

export type WorkflowGroup = "data" | "research" | "code_safety" | "train_score" | "decide_package";

export interface NodeDefinition {
  id: ComponentId;
  /** Plain-language canvas label — what the component does. */
  label: string;
  /** Architecture term shown secondarily in the inspector, never on the canvas. */
  secondaryLabel: string;
  group: WorkflowGroup;
}

export const GROUP_LABELS: Record<WorkflowGroup, string> = {
  data: "Data",
  research: "Research",
  code_safety: "Code & Safety",
  train_score: "Train & Score",
  decide_package: "Decide & Package",
};

export const GROUP_ORDER: WorkflowGroup[] = [
  "data",
  "research",
  "code_safety",
  "train_score",
  "decide_package",
];

// Plain-language canvas labels; architecture terms are secondary (Plan_UI.md #2.2).
export const NODE_REGISTRY: Record<ComponentId, NodeDefinition> = {
  train_data: {
    id: "train_data",
    label: "Training Data",
    secondaryLabel: "Locked KuaiRand-Pure Splits",
    group: "data",
  },
  data_profiler: {
    id: "data_profiler",
    label: "Inspect & Prepare Data",
    secondaryLabel: "Data Profiler & Preprocessor",
    group: "data",
  },
  phase_guard: {
    id: "phase_guard",
    label: "Check Data Safety",
    secondaryLabel: "Integrity Kernel",
    group: "data",
  },
  knowledge_mcp: {
    id: "knowledge_mcp",
    label: "Find Research Evidence",
    secondaryLabel: "Research Knowledge MCP",
    group: "research",
  },
  scientist: {
    id: "scientist",
    label: "Choose the Next Experiment",
    secondaryLabel: "Research Agent",
    group: "research",
  },
  coder: {
    id: "coder",
    label: "Write the Code Change",
    secondaryLabel: "Code & Recovery Agent",
    group: "code_safety",
  },
  pruner: {
    id: "pruner",
    label: "Run Fast Safety Tests",
    secondaryLabel: "Tier 1–3 Execution Funnel",
    group: "code_safety",
  },
  trainer: {
    id: "trainer",
    label: "Train the Model",
    secondaryLabel: "Tier 4 Full Trainer",
    group: "train_score",
  },
  recovery: {
    id: "recovery",
    label: "Recover from Failures",
    secondaryLabel: "Recovery Controller",
    group: "train_score",
  },
  evaluator: {
    id: "evaluator",
    label: "Score on Validation",
    secondaryLabel: "Official Evaluator (evaluate.py)",
    group: "train_score",
  },
  watchdog: {
    id: "watchdog",
    label: "Decide: Continue or Stop",
    secondaryLabel: "Frontier / Convergence Watchdog",
    group: "decide_package",
  },
  ledger: {
    id: "ledger",
    label: "Save Run Evidence",
    secondaryLabel: "Append-Only Event Ledger",
    group: "decide_package",
  },
  finalizer: {
    id: "finalizer",
    label: "Build Final Package",
    secondaryLabel: "Submission Finalizer",
    group: "decide_package",
  },
  submission: {
    id: "submission",
    label: "Verified Predictions",
    secondaryLabel: "predictions.csv",
    group: "decide_package",
  },
};

export const NODE_IDS = Object.keys(NODE_REGISTRY) as ComponentId[];
