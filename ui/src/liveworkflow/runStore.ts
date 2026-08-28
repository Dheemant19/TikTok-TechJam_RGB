import { create } from "zustand";
import { NODES, NodeStatus, RUN_ORDER } from "../data/nodeRegistry";

type RunStatus = "idle" | "running" | "done";

interface RunState {
  nodeStatus: Record<string, NodeStatus>;
  nodeElapsed: Record<string, number>;
  runStatus: RunStatus;
  start: () => void;
  reset: () => void;
}

function idleStatus(): Record<string, NodeStatus> {
  return Object.fromEntries(NODES.map((n) => [n.id, "waiting" as NodeStatus]));
}

let elapsedInterval: ReturnType<typeof setInterval> | undefined;
let runTimeout: ReturnType<typeof setTimeout> | undefined;

function stepThrough(i: number, set: (partial: Partial<RunState>) => void, get: () => RunState) {
  if (i >= RUN_ORDER.length) {
    set({ runStatus: "done" });
    return;
  }
  const id = RUN_ORDER[i];
  set({ nodeStatus: { ...get().nodeStatus, [id]: "running" } });
  const start = Date.now();
  clearInterval(elapsedInterval);
  elapsedInterval = setInterval(() => {
    set({ nodeElapsed: { ...get().nodeElapsed, [id]: Date.now() - start } });
  }, 100);
  const duration = 850 + Math.random() * 450;
  clearTimeout(runTimeout);
  runTimeout = setTimeout(() => {
    clearInterval(elapsedInterval);
    set({ nodeStatus: { ...get().nodeStatus, [id]: "succeeded" } });
    stepThrough(i + 1, set, get);
  }, duration);
}

export const useRunStore = create<RunState>((set, get) => ({
  nodeStatus: idleStatus(),
  nodeElapsed: {},
  runStatus: "idle",
  start: () => {
    if (get().runStatus === "running") return;
    set({ runStatus: "running", nodeStatus: idleStatus(), nodeElapsed: {} });
    stepThrough(0, set, get);
  },
  reset: () => {
    clearInterval(elapsedInterval);
    clearTimeout(runTimeout);
    set({ runStatus: "idle", nodeStatus: idleStatus(), nodeElapsed: {} });
  },
}));
