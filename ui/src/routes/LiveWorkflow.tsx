import { useState } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { WorkflowCanvas } from "@/workflow/WorkflowCanvas";
import { InspectorPresence } from "@/inspector/Inspector";
import { WorkflowScene } from "@/scene3d/WorkflowScene";
import { StageFocusPresence } from "@/scene3d/StageFocusPanel";
import { AutonomyTimeline } from "@/components/AutonomyTimeline";
import { ReplayControls } from "@/components/ReplayControls";
import { NODE_REGISTRY, GROUP_ORDER, NODE_IDS } from "@/workflow/nodeRegistry";
import { STATUS_STYLES } from "@/workflow/statusStyles";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { useWebGLSupport } from "@/hooks/useWebGLSupport";
import type { ComponentId, RunEvent } from "@/api/types";
import canvasStyles from "./LiveWorkflow.module.css";

interface LiveWorkflowProps {
  events: RunEvent[];
  isReplay: boolean;
  replayTotal?: number;
  replayIndex?: number;
  onReplayIndexChange?: (index: number) => void;
  replayPlaying?: boolean;
  onReplayPlayingChange?: (playing: boolean) => void;
  replaySpeed?: 0.5 | 1 | 2 | 4;
  onReplaySpeedChange?: (speed: 0.5 | 1 | 2 | 4) => void;
}

function latestStatusByComponent(events: RunEvent[]) {
  const map = new Map<ComponentId, RunEvent>();
  for (const event of events) map.set(event.component_id, event);
  return map;
}

export function LiveWorkflow({
  events,
  isReplay,
  replayTotal = 0,
  replayIndex = 0,
  onReplayIndexChange,
  replayPlaying = false,
  onReplayPlayingChange,
  replaySpeed = 1,
  onReplaySpeedChange,
}: LiveWorkflowProps) {
  const [selectedComponentId, setSelectedComponentId] = useState<ComponentId | null>(null);
  const [focusExecutionId, setFocusExecutionId] = useState<string | null>(null);
  const isNarrow = useMediaQuery("(max-width: 640px)");
  const reducedMotion = useReducedMotion();
  const webglSupported = useWebGLSupport();
  const statusByComponent = latestStatusByComponent(events);
  // The 3D mission-control scene is the primary experience; narrow screens,
  // reduced motion, and missing WebGL all fall back to the proven 2D graph
  // and side inspector (Plan_UI.md accessibility + PRODUCT.md a11y note).
  const use3D = !isNarrow && !reducedMotion && webglSupported;

  function handleTimelineSelect(componentId: ComponentId, executionId: string) {
    setSelectedComponentId(componentId);
    setFocusExecutionId(executionId);
  }

  function closeDetail() {
    setSelectedComponentId(null);
    setFocusExecutionId(null);
  }

  return (
    <div className={canvasStyles.layout}>
      <div className={canvasStyles.canvasArea}>
        {isNarrow ? (
          <ol className={canvasStyles.mobileList} aria-label="Workflow components in pipeline order">
            {GROUP_ORDER.flatMap((group) =>
              NODE_IDS.filter((id) => NODE_REGISTRY[id].group === group).map((id) => {
                const latest = statusByComponent.get(id);
                const style = STATUS_STYLES[latest?.status ?? "waiting"];
                return (
                  <li key={id}>
                    <button
                      type="button"
                      className={canvasStyles.mobileListItem}
                      data-active={selectedComponentId === id || undefined}
                      onClick={() => setSelectedComponentId(id)}
                    >
                      <span>{NODE_REGISTRY[id].label}</span>
                      <span style={{ color: `var(${style.colorVar})` }}>{style.label}</span>
                    </button>
                  </li>
                );
              }),
            )}
          </ol>
        ) : use3D ? (
          <WorkflowScene events={events} focusedId={selectedComponentId} onSelect={setSelectedComponentId} reducedMotion={reducedMotion} />
        ) : (
          <ReactFlowProvider>
            <WorkflowCanvas events={events} selectedComponentId={selectedComponentId} onSelectComponent={setSelectedComponentId} />
          </ReactFlowProvider>
        )}
      </div>

      {isReplay && onReplayIndexChange && onReplayPlayingChange && onReplaySpeedChange && (
        <ReplayControls
          index={replayIndex}
          total={replayTotal}
          playing={replayPlaying}
          speed={replaySpeed}
          onIndexChange={onReplayIndexChange}
          onPlayingChange={onReplayPlayingChange}
          onSpeedChange={onReplaySpeedChange}
        />
      )}

      <AutonomyTimeline events={events} onSelectRow={handleTimelineSelect} />

      {use3D ? (
        <StageFocusPresence componentId={selectedComponentId} events={events} onClose={closeDetail} focusExecutionId={focusExecutionId} />
      ) : (
        <InspectorPresence componentId={selectedComponentId} events={events} focusExecutionId={focusExecutionId} onClose={closeDetail} />
      )}
    </div>
  );
}

export type { LiveWorkflowProps };
