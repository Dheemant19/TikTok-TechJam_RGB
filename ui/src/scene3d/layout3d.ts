import * as THREE from "three";
import { GROUP_ORDER, NODE_REGISTRY, type WorkflowGroup } from "@/workflow/nodeRegistry";
import type { ComponentId } from "@/api/types";

/**
 * Mission-control amphitheater: groups run left-to-right along a shallow
 * arc (matches the 2D pipeline's reading order exactly), nodes within a
 * group stack at different heights like panels on a control-room wall.
 * Positions are fixed — this is telemetry, not a force-directed toy.
 */
const ARC_RADIUS = 9.5;
const ARC_SPAN = Math.PI * 0.62; // shallow arc, whole pipeline stays in one glance
const GROUP_ROWS: Record<ComponentId, number> = {
  train_data: 0,
  data_profiler: 1,
  phase_guard: 2,
  knowledge_mcp: 0,
  scientist: 1,
  coder: 0,
  pruner: 1,
  trainer: 0,
  evaluator: 1,
  recovery: 2,
  watchdog: 0,
  ledger: 1,
  finalizer: 2,
  submission: 3,
};

const ROW_HEIGHT = 1.9;

export interface NodePlacement {
  id: ComponentId;
  position: THREE.Vector3;
  /** Camera "look toward" direction when focused on this node. */
  forward: THREE.Vector3;
  group: WorkflowGroup;
}

function groupAngle(group: WorkflowGroup): number {
  const index = GROUP_ORDER.indexOf(group);
  const t = GROUP_ORDER.length === 1 ? 0.5 : index / (GROUP_ORDER.length - 1);
  return -ARC_SPAN / 2 + t * ARC_SPAN;
}

export const NODE_PLACEMENTS: Record<ComponentId, NodePlacement> = Object.fromEntries(
  (Object.keys(NODE_REGISTRY) as ComponentId[]).map((id) => {
    const definition = NODE_REGISTRY[id];
    const angle = groupAngle(definition.group);
    const row = GROUP_ROWS[id];
    const x = Math.sin(angle) * ARC_RADIUS;
    const z = -Math.cos(angle) * ARC_RADIUS;
    const y = row * ROW_HEIGHT - ROW_HEIGHT * 0.6;
    const position = new THREE.Vector3(x, y, z);
    const forward = position.clone().normalize().multiplyScalar(-1);
    return [id, { id, position, forward, group: definition.group }];
  }),
) as Record<ComponentId, NodePlacement>;

export const NODE_ORDER: ComponentId[] = Object.keys(NODE_REGISTRY) as ComponentId[];

/** Overview camera: pulled back so every node is in frame at once. */
export const OVERVIEW_CAMERA_POSITION = new THREE.Vector3(0, 2.9, 12.5);
export const OVERVIEW_CAMERA_TARGET = new THREE.Vector3(0, 1.1, -1);

/** Focus camera: close in front of the node, framing it large. */
export function focusCameraPose(id: ComponentId): { position: THREE.Vector3; target: THREE.Vector3 } {
  const placement = NODE_PLACEMENTS[id];
  const offset = placement.position.clone().normalize().multiplyScalar(4.4);
  const position = placement.position.clone().add(offset).add(new THREE.Vector3(0, 1.1, 0));
  const target = placement.position.clone().add(new THREE.Vector3(0, 0.4, 0));
  return { position, target };
}
