import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Text, RoundedBox } from "@react-three/drei";
import * as THREE from "three";
import type { ComponentId, ComponentStatus } from "@/api/types";
import { NODE_REGISTRY } from "@/workflow/nodeRegistry";
import { STATUS_VISUALS } from "./statusVisuals";
import { NODE_PLACEMENTS } from "./layout3d";

interface StageNodeProps {
  id: ComponentId;
  status: ComponentStatus;
  focused: boolean;
  dimmed: boolean;
  reducedMotion: boolean;
  onSelect: (id: ComponentId) => void;
}

const CARD_WIDTH = 2.4;
const CARD_HEIGHT = 1.3;
const CARD_DEPTH = 0.16;
const DOT_RADIUS = 0.14;

/** One n8n-style card: white rounded panel, a colored status dot, plain-language label. */
export function StageNode({ id, status, focused, dimmed, reducedMotion, onSelect }: StageNodeProps) {
  const groupRef = useRef<THREE.Group>(null);
  const dotRef = useRef<THREE.Mesh>(null);
  const visual = STATUS_VISUALS[status];
  const placement = NODE_PLACEMENTS[id];
  const definition = NODE_REGISTRY[id];
  const pulsePhaseRef = useRef(Math.random() * Math.PI * 2);

  const dotMaterial = useMemo(() => new THREE.MeshStandardMaterial({ color: visual.dot, roughness: 0.4, metalness: 0.05 }), [visual.dot]);

  useFrame((_state, delta) => {
    if (dotRef.current) {
      const targetScale = visual.pulses && !reducedMotion ? 1 + (Math.sin((pulsePhaseRef.current += delta * 3.2)) + 1) * 0.18 : 1;
      dotRef.current.scale.setScalar(reducedMotion ? targetScale : THREE.MathUtils.damp(dotRef.current.scale.x, targetScale, 8, delta));
    }
    if (groupRef.current) {
      const targetY = placement.position.y + (focused ? 0.14 : 0);
      groupRef.current.position.y = reducedMotion ? targetY : THREE.MathUtils.damp(groupRef.current.position.y, targetY, 8, delta);
    }
  });

  return (
    <group
      ref={groupRef}
      position={placement.position}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(id);
      }}
      onPointerOver={(event) => {
        event.stopPropagation();
        document.body.style.cursor = "pointer";
      }}
      onPointerOut={() => {
        document.body.style.cursor = "auto";
      }}
    >
      {/* Card */}
      <RoundedBox args={[CARD_WIDTH, CARD_HEIGHT, CARD_DEPTH]} radius={0.14} smoothness={4} castShadow receiveShadow>
        <meshStandardMaterial
          color={dimmed ? "#eef0f3" : "#ffffff"}
          roughness={0.55}
          metalness={0}
        />
      </RoundedBox>
      {/* Border ring — a hair larger, darker box behind the card so the edge reads without relying on shadow alone. */}
      <mesh position={[0, 0, -0.01]}>
        <boxGeometry args={[CARD_WIDTH + 0.03, CARD_HEIGHT + 0.03, CARD_DEPTH * 0.6]} />
        <meshStandardMaterial color={focused ? visual.dot : "#d5d8de"} roughness={0.7} />
      </mesh>
      {/* Status dot, top-left — the one thing on the card that carries color. */}
      <mesh ref={dotRef} position={[-CARD_WIDTH / 2 + 0.26, CARD_HEIGHT / 2 - 0.24, CARD_DEPTH / 2 + 0.02]} material={dotMaterial}>
        <circleGeometry args={[DOT_RADIUS, 20]} />
      </mesh>
      {/* Label */}
      <Text
        position={[-CARD_WIDTH / 2 + 0.5, 0.1, CARD_DEPTH / 2 + 0.02]}
        fontSize={0.19}
        color={dimmed ? "#9aa1ad" : "#171a1f"}
        anchorX="left"
        anchorY="middle"
        maxWidth={CARD_WIDTH - 0.7}
        textAlign="left"
        material-toneMapped={false}
      >
        {definition.label}
      </Text>
      <Text
        position={[-CARD_WIDTH / 2 + 0.5, -0.28, CARD_DEPTH / 2 + 0.02]}
        fontSize={0.13}
        color={visual.text}
        anchorX="left"
        anchorY="middle"
        material-toneMapped={false}
      >
        {visual.label.toUpperCase()}
      </Text>
    </group>
  );
}
