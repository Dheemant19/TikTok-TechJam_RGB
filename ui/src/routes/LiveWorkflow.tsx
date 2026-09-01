import { LiveWorkflowCanvas } from "../liveworkflow/LiveWorkflowCanvas";
import { SessionChat } from "../components/SessionChat";
import { StageListFallback } from "../components/StageListFallback";
import { useReducedMotion } from "../hooks/useReducedMotion";
import { useMediaQuery } from "../hooks/useMediaQuery";

export function LiveWorkflow() {
  const reducedMotion = useReducedMotion();
  const isNarrow = useMediaQuery("(max-width: 720px)");

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {isNarrow ? (
          <StageListFallback reducedMotion={reducedMotion} />
        ) : (
          <LiveWorkflowCanvas reducedMotion={reducedMotion} isNarrow={false} idleEdgeSpeed={3} />
        )}
      </div>
      <SessionChat />
    </div>
  );
}
