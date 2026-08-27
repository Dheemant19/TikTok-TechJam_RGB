import { Suspense, useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import type { ComponentId, ComponentStatus, RunEvent } from "@/api/types";
import { NODE_ORDER } from "./layout3d";
import { StageNode } from "./StageNode";
import { Connections } from "./Connections";
import { CameraRig } from "./CameraRig";
import { SceneEnvironment } from "./Environment";

interface WorkflowSceneProps {
  events: RunEvent[];
  focusedId: ComponentId | null;
  onSelect: (id: ComponentId | null) => void;
  reducedMotion: boolean;
}

function deriveStatusByComponent(events: RunEvent[]): Map<ComponentId, ComponentStatus> {
  const map = new Map<ComponentId, ComponentStatus>();
  for (const event of events) map.set(event.component_id, event.status);
  return map;
}

export function WorkflowScene({ events, focusedId, onSelect, reducedMotion }: WorkflowSceneProps) {
  const statusByComponent = useMemo(() => deriveStatusByComponent(events), [events]);

  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      camera={{ fov: 42, near: 0.1, far: 200 }}
      onPointerMissed={() => onSelect(null)}
    >
      <Suspense fallback={null}>
        <SceneEnvironment />
        <CameraRig focusedId={focusedId} reducedMotion={reducedMotion} />
        <Connections statusByComponent={statusByComponent} reducedMotion={reducedMotion} />
        {NODE_ORDER.map((id) => (
          <StageNode
            key={id}
            id={id}
            status={statusByComponent.get(id) ?? "waiting"}
            focused={focusedId === id}
            dimmed={focusedId !== null && focusedId !== id}
            reducedMotion={reducedMotion}
            onSelect={onSelect}
          />
        ))}
      </Suspense>
    </Canvas>
  );
}
