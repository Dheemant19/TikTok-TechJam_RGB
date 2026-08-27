import { useMemo } from "react";
import * as THREE from "three";

/** n8n-style canvas floor: a light dotted grid — the literal surface this tool represents, not decoration. No solid ground plane, so no false horizon reads as a hill. */
function DotGrid() {
  const geometry = useMemo(() => {
    const spacing = 1.1;
    const extent = 26;
    const positions: number[] = [];
    for (let x = -extent; x <= extent; x += spacing) {
      for (let z = -extent; z <= extent; z += spacing) {
        positions.push(x, 0, z);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    return geo;
  }, []);

  return (
    <points geometry={geometry} position={[0, -1.6, 0]}>
      <pointsMaterial color="#c7cbd3" size={0.05} sizeAttenuation transparent opacity={0.85} />
    </points>
  );
}

/** Bright, even, product-shot lighting — clarity over mood (user feedback: no dark theatrics). */
export function SceneEnvironment() {
  return (
    <>
      <color attach="background" args={["#eef0f3"]} />
      <ambientLight intensity={1.0} color="#ffffff" />
      <directionalLight position={[8, 14, 8]} intensity={0.9} color="#ffffff" castShadow shadow-mapSize={[1024, 1024]} />
      <directionalLight position={[-8, 8, -6]} intensity={0.4} color="#ffffff" />
      <hemisphereLight args={["#ffffff", "#dfe2e8", 0.5]} />
      <DotGrid />
    </>
  );
}
