import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import styles from "./WorkflowCanvas.module.css";
import { buildInitialEdges, buildInitialNodes } from "./layout";
import { WorkflowNode, type WorkflowNodeData } from "./WorkflowNode";
import type { ComponentId, ComponentStatus, RunEvent } from "@/api/types";

const NODE_TYPES = { workflow: WorkflowNode };

interface WorkflowCanvasProps {
  events: RunEvent[];
  selectedComponentId: ComponentId | null;
  onSelectComponent: (componentId: ComponentId | null) => void;
}

/** Latest status/started-at/reason per component, derived from ordered events. */
function deriveComponentState(events: RunEvent[]) {
  const state = new Map<ComponentId, { status: ComponentStatus; startedAt?: string; reason?: string }>();
  for (const event of events) {
    const previous = state.get(event.component_id);
    const startedAt = event.status === "running" ? event.occurred_at : previous?.startedAt;
    const reason =
      event.status === "failed" || event.status === "blocked" || event.status === "rejected"
        ? event.plain_summary
        : undefined;
    state.set(event.component_id, { status: event.status, startedAt, reason });
  }
  return state;
}

export function WorkflowCanvas({ events, selectedComponentId, onSelectComponent }: WorkflowCanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState(buildInitialNodes());
  const [edges, , onEdgesChange] = useEdgesState(buildInitialEdges());
  const { fitView } = useReactFlow();
  const containerRef = useRef<HTMLDivElement>(null);

  const componentState = useMemo(() => deriveComponentState(events), [events]);

  useEffect(() => {
    setNodes((current) =>
      current.map((node) => {
        const latest = componentState.get(node.id as ComponentId);
        if (!latest) return node;
        const data = node.data as WorkflowNodeData;
        if (data.status === latest.status && data.startedAt === latest.startedAt && data.reason === latest.reason) {
          return node;
        }
        return { ...node, data: { ...data, ...latest }, selected: node.id === selectedComponentId };
      }),
    );
  }, [componentState, setNodes, selectedComponentId]);

  const handleNodeClick = useCallback<NodeMouseHandler>(
    (_event, node) => {
      onSelectComponent(node.id as ComponentId);
    },
    [onSelectComponent],
  );

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "f" || event.key === "F") {
        if (document.activeElement?.tagName === "INPUT" || document.activeElement?.tagName === "TEXTAREA") return;
        fitView({ duration: 300 });
      }
      if (event.key === "Escape") {
        onSelectComponent(null);
      }
    };
    const container = containerRef.current;
    container?.addEventListener("keydown", handleKeyDown);
    return () => container?.removeEventListener("keydown", handleKeyDown);
  }, [fitView, onSelectComponent]);

  return (
    <div ref={containerRef} style={{ width: "100%", height: "100%" }}>
      <ReactFlow
        className={styles.canvas}
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        nodeTypes={NODE_TYPES}
        // Users may temporarily reposition nodes; this is a session-local
        // preference only and never changes edges/execution order.
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
        fitView
        minZoom={0.3}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={24} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable nodeStrokeWidth={2} />
      </ReactFlow>
    </div>
  );
}
