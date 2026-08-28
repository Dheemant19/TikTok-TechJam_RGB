import { useState } from "react";
import type { OverlayRect } from "./InspectorPanel";

export function useFlipInspector(reducedMotion: boolean) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [overlayRect, setOverlayRect] = useState<OverlayRect | null>(null);
  const [overlayOpen, setOverlayOpen] = useState(false);

  const openNode = (id: string, rect: OverlayRect) => {
    setSelectedId(id);
    setOverlayRect(rect);
    setOverlayOpen(false);
    if (reducedMotion) {
      setOverlayOpen(true);
    } else {
      requestAnimationFrame(() => requestAnimationFrame(() => setOverlayOpen(true)));
    }
  };

  const closeInspector = () => {
    setOverlayOpen(false);
    if (reducedMotion) {
      setSelectedId(null);
      setOverlayRect(null);
    } else {
      setTimeout(() => {
        setSelectedId(null);
        setOverlayRect(null);
      }, 460);
    }
  };

  return { selectedId, overlayRect, overlayOpen, openNode, closeInspector };
}
