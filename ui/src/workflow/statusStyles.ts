import {
  CheckCircle2,
  CircleDashed,
  CircleMinus,
  CirclePause,
  CircleX,
  Clock,
  SkipForward,
  ShieldAlert,
  type LucideIcon,
} from "lucide-react";
import type { ComponentStatus } from "@/api/types";

interface StatusStyle {
  icon: LucideIcon;
  colorVar: string;
  label: string;
}

// Shape + icon + text + color together (Plan_UI.md #2.4). No glow, no
// gradients, no pulsing animation on any state.
export const STATUS_STYLES: Record<ComponentStatus, StatusStyle> = {
  waiting: { icon: CircleDashed, colorVar: "--status-waiting", label: "Waiting" },
  ready: { icon: CircleDashed, colorVar: "--status-ready", label: "Ready" },
  running: { icon: Clock, colorVar: "--status-running", label: "Running" },
  paused: { icon: CirclePause, colorVar: "--status-paused", label: "Paused" },
  succeeded: { icon: CheckCircle2, colorVar: "--status-succeeded", label: "Succeeded" },
  failed: { icon: CircleX, colorVar: "--status-failed", label: "Failed" },
  rejected: { icon: CircleMinus, colorVar: "--status-rejected", label: "Experiment rejected" },
  skipped: { icon: SkipForward, colorVar: "--status-skipped", label: "Skipped" },
  blocked: { icon: ShieldAlert, colorVar: "--status-blocked", label: "Blocked" },
};

export function formatElapsed(startedAt: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}
