import { useCallback, useEffect, useRef, useState } from "react";
import type { FocusPhase, OverlayRect, StageFocusState } from "./stageNavigation";

const CLOSE_TRANSITION_MS = 650;
const STAGE_TRANSITION_MS = 1120;

export function useFlipInspector(reducedMotion: boolean) {
  const [state, setState] = useState<StageFocusState>({
    selectedNodeId: null,
    previousNodeId: null,
    originRect: null,
    phase: "closed",
    activeSection: "summary",
    isAdvancing: false,
  });
  const selectedRef = useRef<string | null>(null);
  const phaseRef = useRef<FocusPhase>("closed");
  const timerRef = useRef<number | null>(null);
  const openFrameRef = useRef<number | null>(null);
  const openFrame2Ref = useRef<number | null>(null);
  const originFocusRef = useRef<HTMLElement | null>(null);

  const clearScheduledWork = useCallback(() => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    if (openFrameRef.current !== null) window.cancelAnimationFrame(openFrameRef.current);
    if (openFrame2Ref.current !== null) window.cancelAnimationFrame(openFrame2Ref.current);
    timerRef.current = null;
    openFrameRef.current = null;
    openFrame2Ref.current = null;
  }, []);

  const setPhase = useCallback((phase: FocusPhase) => {
    phaseRef.current = phase;
    setState((current) => ({ ...current, phase, isAdvancing: phase === "transitioning" }));
  }, []);

  const restoreFocus = useCallback((nodeId: string | null) => {
    const origin = originFocusRef.current;
    if (origin?.isConnected) {
      origin.focus();
      return;
    }
    if (!nodeId) return;
    document.querySelector<HTMLElement>(`[data-node-id="${nodeId}"]`)?.focus();
  }, []);

  const finishClose = useCallback(() => {
    const nodeId = selectedRef.current;
    clearScheduledWork();
    selectedRef.current = null;
    phaseRef.current = "closed";
    setState({
      selectedNodeId: null,
      previousNodeId: null,
      originRect: null,
      phase: "closed",
      activeSection: "summary",
      isAdvancing: false,
    });
    window.requestAnimationFrame(() => {
      restoreFocus(nodeId);
      // The overlay's inert cleanup and the canvas visibility update happen
      // in the same commit; a second frame keeps focus restoration reliable
      // across browsers that defer either one.
      window.requestAnimationFrame(() => restoreFocus(nodeId));
    });
  }, [clearScheduledWork, restoreFocus]);

  useEffect(() => () => clearScheduledWork(), [clearScheduledWork]);

  // `rect` is the clicked card's `getBoundingClientRect()`, read synchronously
  // inside the click handler in `NodeCard`/`LiveWorkflowCanvas.handleOpen`
  // (never cached ahead of time). `getBoundingClientRect()` always resolves
  // post-transform viewport coordinates, so it already accounts for the
  // canvas's pan/zoom `transform: translate(...) scale(...)` -- no separate
  // measurement or transform math is needed here (AGENTS.md #3).
  const openNode = useCallback((id: string, rect: OverlayRect) => {
    clearScheduledWork();
    if (!selectedRef.current || phaseRef.current === "closed" || phaseRef.current === "closing") {
      const active = document.activeElement;
      originFocusRef.current = active instanceof HTMLElement && active !== document.body ? active : null;
    }
    selectedRef.current = id;
    phaseRef.current = reducedMotion ? "open" : "opening";
    setState({
      selectedNodeId: id,
      previousNodeId: null,
      originRect: rect,
      phase: phaseRef.current,
      activeSection: "summary",
      isAdvancing: false,
    });
    if (reducedMotion) {
      return;
    }
    openFrameRef.current = window.requestAnimationFrame(() => {
      openFrame2Ref.current = window.requestAnimationFrame(() => {
        if (selectedRef.current === id && phaseRef.current === "opening") setPhase("open");
      });
    });
  }, [clearScheduledWork, reducedMotion, setPhase]);

  const navigateNode = useCallback((id: string) => {
    const currentId = selectedRef.current;
    if (!currentId || currentId === id || phaseRef.current === "closing" || phaseRef.current === "transitioning") return;
    clearScheduledWork();
    selectedRef.current = id;
    if (reducedMotion) {
      phaseRef.current = "open";
      setState((current) => ({ ...current, selectedNodeId: id, previousNodeId: null, phase: "open", activeSection: "summary", isAdvancing: false }));
      return;
    }
    phaseRef.current = "transitioning";
    setState((current) => ({ ...current, selectedNodeId: id, previousNodeId: currentId, phase: "transitioning", activeSection: "summary", isAdvancing: true }));
    timerRef.current = window.setTimeout(() => {
      if (selectedRef.current !== id || phaseRef.current !== "transitioning") return;
      phaseRef.current = "open";
      setState((current) => ({ ...current, previousNodeId: null, phase: "open", isAdvancing: false }));
      timerRef.current = null;
    }, STAGE_TRANSITION_MS);
  }, [clearScheduledWork, reducedMotion]);

  const closeInspector = useCallback(() => {
    if (!selectedRef.current || phaseRef.current === "closing") return;
    clearScheduledWork();
    if (reducedMotion) {
      finishClose();
      return;
    }
    setPhase("closing");
    timerRef.current = window.setTimeout(finishClose, CLOSE_TRANSITION_MS);
  }, [clearScheduledWork, finishClose, reducedMotion, setPhase]);

  const overlayOpen = state.phase === "open" || state.phase === "transitioning";

  return {
    selectedId: state.selectedNodeId,
    previousNodeId: state.previousNodeId,
    overlayRect: state.originRect,
    overlayOpen,
    phase: state.phase,
    activeSection: state.activeSection,
    isAdvancing: state.isAdvancing,
    openNode,
    navigateNode,
    closeInspector,
  };
}
