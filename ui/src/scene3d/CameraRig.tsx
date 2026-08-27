import { useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import type { ComponentId } from "@/api/types";
import { OVERVIEW_CAMERA_POSITION, OVERVIEW_CAMERA_TARGET, focusCameraPose } from "./layout3d";

interface CameraRigProps {
  focusedId: ComponentId | null;
  reducedMotion: boolean;
}

/**
 * Exactly two camera states — full-pipeline overview and single-node focus —
 * joined by one continuous, interruptible damped path. The overview camera
 * holds still: it is a canvas the viewer reads, not a showreel (n8n has no
 * ambient camera motion either — motion only happens when the user acts).
 */
export function CameraRig({ focusedId, reducedMotion }: CameraRigProps) {
  const { camera } = useThree();
  const currentTargetRef = useRef(new THREE.Vector3().copy(OVERVIEW_CAMERA_TARGET));
  const initializedRef = useRef(false);

  if (!initializedRef.current) {
    camera.position.copy(OVERVIEW_CAMERA_POSITION);
    initializedRef.current = true;
  }

  useFrame((_state, delta) => {
    const pose = focusedId ? focusCameraPose(focusedId) : { position: OVERVIEW_CAMERA_POSITION, target: OVERVIEW_CAMERA_TARGET };

    if (reducedMotion) {
      camera.position.copy(pose.position);
      currentTargetRef.current.copy(pose.target);
    } else {
      const damping = focusedId ? 4.2 : 3.6;
      camera.position.x = THREE.MathUtils.damp(camera.position.x, pose.position.x, damping, delta);
      camera.position.y = THREE.MathUtils.damp(camera.position.y, pose.position.y, damping, delta);
      camera.position.z = THREE.MathUtils.damp(camera.position.z, pose.position.z, damping, delta);
      currentTargetRef.current.x = THREE.MathUtils.damp(currentTargetRef.current.x, pose.target.x, damping, delta);
      currentTargetRef.current.y = THREE.MathUtils.damp(currentTargetRef.current.y, pose.target.y, damping, delta);
      currentTargetRef.current.z = THREE.MathUtils.damp(currentTargetRef.current.z, pose.target.z, damping, delta);
    }
    camera.lookAt(currentTargetRef.current);
  });

  return null;
}
