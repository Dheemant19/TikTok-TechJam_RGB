import * as THREE from "three";
import type { ComponentStatus } from "@/api/types";

export interface StatusVisual {
  /** Status dot fill — vivid, reads clearly against the white card. */
  dot: THREE.Color;
  /** Status label text — darker variant of the same hue so it stays ≥4.5:1 on white. */
  text: THREE.Color;
  /** Running nodes scale-pulse their dot; everything else holds still. */
  pulses: boolean;
  label: string;
}

const NEUTRAL_DOT = new THREE.Color("#9aa1ad");
const NEUTRAL_TEXT = new THREE.Color("#6b7280");
const AMBER_DOT = new THREE.Color("#f5a623");
const AMBER_TEXT = new THREE.Color("#a15c00");
const ALARM_DOT = new THREE.Color("#ef4444");
const ALARM_TEXT = new THREE.Color("#b3271b");

export const STATUS_VISUALS: Record<ComponentStatus, StatusVisual> = {
  waiting: { dot: NEUTRAL_DOT, text: NEUTRAL_TEXT, pulses: false, label: "Waiting" },
  ready: { dot: NEUTRAL_DOT, text: NEUTRAL_TEXT, pulses: false, label: "Ready" },
  running: { dot: AMBER_DOT, text: AMBER_TEXT, pulses: true, label: "Running" },
  paused: { dot: NEUTRAL_DOT, text: NEUTRAL_TEXT, pulses: false, label: "Paused" },
  succeeded: { dot: AMBER_DOT, text: AMBER_TEXT, pulses: false, label: "Succeeded" },
  failed: { dot: ALARM_DOT, text: ALARM_TEXT, pulses: false, label: "Failed" },
  rejected: { dot: NEUTRAL_DOT, text: NEUTRAL_TEXT, pulses: false, label: "Experiment rejected" },
  skipped: { dot: NEUTRAL_DOT, text: NEUTRAL_TEXT, pulses: false, label: "Skipped" },
  blocked: { dot: ALARM_DOT, text: ALARM_TEXT, pulses: true, label: "Blocked" },
};
