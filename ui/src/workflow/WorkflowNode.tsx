import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { motion } from "motion/react";
import { NODE_REGISTRY } from "./nodeRegistry";
import { STATUS_STYLES, formatElapsed } from "./statusStyles";
import type { ComponentId, ComponentStatus } from "@/api/types";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { useElapsedTick } from "@/hooks/useElapsedTick";
import styles from "./WorkflowNode.module.css";

export interface WorkflowNodeData extends Record<string, unknown> {
  componentId: ComponentId;
  status?: ComponentStatus;
  startedAt?: string;
  reason?: string;
}

function WorkflowNodeImpl({ data, selected }: NodeProps) {
  const nodeData = data as WorkflowNodeData;
  const definition = NODE_REGISTRY[nodeData.componentId];
  const status: ComponentStatus = nodeData.status ?? "waiting";
  const style = STATUS_STYLES[status];
  const Icon = style.icon;
  const reducedMotion = useReducedMotion();
  // Re-render once a second only while a node is actually running, so the
  // elapsed-time label stays live without redrawing the whole canvas.
  useElapsedTick(status === "running");

  return (
    <motion.div
      className={styles.node}
      data-selected={selected || undefined}
      data-status={status}
      style={{ borderColor: `var(${style.colorVar})` }}
      layout={!reducedMotion}
      transition={
        reducedMotion
          ? { duration: 0.001 }
          : { type: "spring", bounce: 0, duration: 0.36 }
      }
      role="button"
      tabIndex={0}
      aria-label={`${definition.label}, ${style.label}${nodeData.reason ? `: ${nodeData.reason}` : ""}`}
    >
      <Handle type="target" position={Position.Left} className={styles.handle} />
      <div className={styles.header}>
        <Icon size={16} color={`var(${style.colorVar})`} aria-hidden="true" />
        <span className={styles.label}>{definition.label}</span>
      </div>
      <div className={styles.statusRow} style={{ color: `var(${style.colorVar})` }}>
        {status === "running" ? (
          <>
            <span className={styles.dot} aria-hidden="true" />
            <span>{nodeData.startedAt ? formatElapsed(nodeData.startedAt) : style.label}</span>
          </>
        ) : (
          <span>{status === "failed" || status === "blocked" ? (nodeData.reason ?? style.label) : style.label}</span>
        )}
      </div>
      <Handle type="source" position={Position.Right} className={styles.handle} />
    </motion.div>
  );
}

export const WorkflowNode = memo(WorkflowNodeImpl);
