import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { ComponentId, ComponentStatus } from "@/api/types";
import { PRIMARY_EDGES, RECOVERY_EDGES } from "@/workflow/layout";
import { NODE_PLACEMENTS } from "./layout3d";

interface ConnectionsProps {
  statusByComponent: Map<ComponentId, ComponentStatus>;
  reducedMotion: boolean;
}

const AMBER = new THREE.Color("#f5a623");
const IDLE = new THREE.Color("#b8bcc4");

function edgeCurve(source: ComponentId, target: ComponentId): THREE.CatmullRomCurve3 {
  const a = NODE_PLACEMENTS[source].position;
  const b = NODE_PLACEMENTS[target].position;
  const mid = a.clone().lerp(b, 0.5);
  mid.y += 0.85; // arcs clear over the card volume instead of cutting through it
  return new THREE.CatmullRomCurve3([a, mid, b]);
}

function EdgeLine({ source, target, active, dashed }: { source: ComponentId; target: ComponentId; active: boolean; dashed: boolean }) {
  const geometry = useMemo(() => {
    const curve = edgeCurve(source, target);
    const points = curve.getPoints(24);
    return new THREE.BufferGeometry().setFromPoints(points);
  }, [source, target]);

  return (
    <primitive object={new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: active ? AMBER : IDLE, transparent: true, opacity: active ? 1 : dashed ? 0.45 : 0.7 }))} />
  );
}

/** A single point of light traveling along the currently active data path — real signal, not ambient decoration. */
function FlowPulse({ source, target }: { source: ComponentId; target: ComponentId }) {
  const meshRef = useRef<THREE.Mesh>(null);
  const curve = useMemo(() => edgeCurve(source, target), [source, target]);
  const tRef = useRef(0);

  useFrame((_state, delta) => {
    tRef.current = (tRef.current + delta * 0.5) % 1;
    const point = curve.getPointAt(tRef.current);
    meshRef.current?.position.copy(point);
  });

  return (
    <mesh ref={meshRef}>
      <sphereGeometry args={[0.06, 12, 12]} />
      <meshStandardMaterial color={AMBER} emissive={AMBER} emissiveIntensity={2} toneMapped={false} />
    </mesh>
  );
}

/** Renders the fixed pipeline routing and highlights whichever edge currently carries real activity. */
export function Connections({ statusByComponent, reducedMotion }: ConnectionsProps) {
  const activeIds = useMemo(() => {
    const running = new Set<ComponentId>();
    statusByComponent.forEach((status, id) => {
      if (status === "running") running.add(id);
    });
    return running;
  }, [statusByComponent]);

  const activeEdges = useMemo(
    () => PRIMARY_EDGES.filter(([source, target]) => activeIds.has(source) || activeIds.has(target)),
    [activeIds],
  );

  return (
    <group>
      {PRIMARY_EDGES.map(([source, target]) => (
        <EdgeLine key={`${source}->${target}`} source={source} target={target} active={activeIds.has(source) || activeIds.has(target)} dashed={false} />
      ))}
      {RECOVERY_EDGES.map(([source, target]) => (
        <EdgeLine key={`${source}~>${target}`} source={source} target={target} active={activeIds.has(source) || activeIds.has(target)} dashed />
      ))}
      {!reducedMotion && activeEdges.map(([source, target]) => <FlowPulse key={`pulse-${source}-${target}`} source={source} target={target} />)}
    </group>
  );
}
