import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { NODES, type NodeStatus } from "../data/nodeRegistry";
import { laneColorFor, NODE_DETAILS } from "./laneData";
import { FocusArchitecturePane } from "./FocusArchitecturePane";
import { StageDetailScroller } from "./StageDetailScroller";
import { statusMeta } from "./NodeCard";
import { buildNodeDetail } from "./nodeDetail";
import { useRunStore } from "./runStore";
import {
  DETAIL_SECTIONS,
  laneMetaFor,
  nextStageId,
  nodeForId,
  stageProgressLabel,
  type DetailSectionId,
  type FocusPhase,
  type OverlayRect,
} from "./stageNavigation";
import type { Vec2 } from "./laneData";

interface Props {
  nodeId: string | null;
  previousNodeId: string | null;
  phase: FocusPhase;
  overlayOpen: boolean;
  overlayRect: OverlayRect | null;
  positions: Record<string, Vec2>;
  nodeStatus: Record<string, NodeStatus>;
  nodeElapsed: Record<string, number>;
  reducedMotion: boolean;
  isNarrow: boolean;
  onClose: () => void;
  onNavigate: (nodeId: string) => void;
}

type FocusStyle = CSSProperties & {
  "--focus-origin-top": string;
  "--focus-origin-right": string;
  "--focus-origin-bottom": string;
  "--focus-origin-left": string;
  "--focus-origin-radius": string;
  "--focus-lane-a": string;
  "--focus-lane-b": string;
  "--focus-lane-shadow": string;
};

function sectionLabel(id: DetailSectionId): string {
  return DETAIL_SECTIONS.find((section) => section.id === id)?.label ?? "Summary";
}

export function StageFocusView({
  nodeId,
  previousNodeId,
  phase,
  overlayOpen,
  overlayRect,
  positions,
  nodeStatus,
  nodeElapsed,
  reducedMotion,
  isNarrow,
  onClose,
  onNavigate,
}: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const focusLayerRef = useRef<HTMLDivElement>(null);
  const [activeSection, setActiveSection] = useState<DetailSectionId>("summary");

  // Keep hooks mounted while the closing animation clears the selected id.
  // The fallback also keeps hook order stable when the component is mounted before opening.
  const node = nodeForId(nodeId) ?? NODES[0];
  const nodeStates = useRunStore((state) => state.nodeStates);
  const detail = useMemo(() => buildNodeDetail(node, nodeStates, NODE_DETAILS[node.id]), [node, nodeStates]);

  const nextId = nextStageId(node.id);
  const nextNode = nodeForId(nextId);
  const colors = laneColorFor(node);
  const status = nodeStatus[node.id] ?? "waiting";
  const elapsedMs = nodeElapsed[node.id] ?? 0;
  const stageStatus = statusMeta(status, node.isRecovery);
  const origin = overlayRect ?? { left: 0, top: 0, width: 0, height: 0 };
  const rootStyle: FocusStyle = {
    "--focus-origin-top": `${Math.max(0, origin.top)}px`,
    "--focus-origin-right": `${Math.max(0, origin.left + origin.width)}px`,
    "--focus-origin-bottom": `${Math.max(0, origin.top + origin.height)}px`,
    "--focus-origin-left": `${Math.max(0, origin.left)}px`,
    "--focus-origin-radius": `${Math.max(18, Math.min(26, origin.height / 5 || 18))}px`,
    "--focus-lane-a": colors.a,
    "--focus-lane-b": colors.b,
    "--focus-lane-shadow": colors.shadow,
  };

  useEffect(() => {
    if (!nodeId) return;
    setActiveSection("summary");
  }, [node.id, nodeId]);

  useEffect(() => {
    if (!nodeId) return;
    let active = true;
    const timer = window.setTimeout(() => {
      if (active) closeRef.current?.focus();
    }, reducedMotion ? 0 : 720);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [node.id, nodeId, reducedMotion]);

  useEffect(() => {
    const root = focusLayerRef.current;
    if (!root) return;
    const isolated: Array<{ element: HTMLElement; inert: boolean; ariaHidden: string | null }> = [];
    let branch: HTMLElement | null = root;
    while (branch) {
      const parent: HTMLElement | null = branch.parentElement;
      if (!parent) break;
      for (const sibling of Array.from(parent.children)) {
        if (!(sibling instanceof HTMLElement) || sibling === branch) continue;
        isolated.push({ element: sibling, inert: sibling.hasAttribute("inert"), ariaHidden: sibling.getAttribute("aria-hidden") });
        sibling.setAttribute("inert", "");
        sibling.setAttribute("aria-hidden", "true");
      }
      branch = parent;
      if (parent === document.body) break;
    }
    return () => {
      isolated.forEach(({ element, inert, ariaHidden }) => {
        if (!inert) element.removeAttribute("inert");
        if (ariaHidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", ariaHidden);
      });
    };
  }, [nodeId]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    onClose();
  };

  const announcement = `${node.label}. ${stageStatus.text}. ${sectionLabel(activeSection)} section.`;
  const transitionScene = phase === "transitioning" && previousNodeId !== null;

  if (!nodeId || !nodeForId(nodeId)) return null;

  return (
    <div
      ref={focusLayerRef}
      className={`stage-focus-root ${reducedMotion ? "is-reduced" : ""} ${isNarrow ? "is-narrow" : ""}`}
      data-focus-phase={phase}
      onKeyDown={handleKeyDown}
    >
      <button type="button" className={`stage-focus-backdrop ${phase !== "closing" ? "is-visible" : ""}`} onClick={onClose} aria-label="Close stage focus" tabIndex={-1} />

      <section
        className={`stage-focus-shell is-${phase} ${overlayOpen ? "is-interactive" : ""}`}
        style={rootStyle}
        role="dialog"
        aria-modal="true"
        aria-labelledby="stage-focus-title"
        aria-describedby="summary-heading"
        aria-label={`Stage details for ${node.label}`}
      >
        <div className="stage-focus__content">
          <header className="stage-focus__header">
            <div className="stage-focus__header-copy">
              <div className="stage-focus__header-meta">
                <span>{stageProgressLabel(node.id)}</span>
                <span aria-hidden="true">/</span>
                <span>{laneMetaFor(node.id)}</span>
              </div>
              <h1 id="stage-focus-title">{node.label}</h1>
              <div className="stage-focus__status-line">
                <span className="stage-focus__status" style={{ color: stageStatus.color }}>
                  <span className="stage-focus__status-dot" style={{ background: stageStatus.dot }} aria-hidden="true" />
                  {stageStatus.text}
                </span>
                {status === "running" && <span className="mono tabular">Live for {(elapsedMs / 1000).toFixed(1)}s</span>}
                <span className="stage-focus__readonly">Read-only evidence</span>
              </div>
            </div>

            <div className="stage-focus__section-progress" aria-label={`Current detail section: ${sectionLabel(activeSection)}`}>
              {DETAIL_SECTIONS.map((section) => (
                <span key={section.id} className={activeSection === section.id ? "is-active" : ""} aria-current={activeSection === section.id ? "true" : undefined}>
                  {section.label}
                </span>
              ))}
            </div>

            <button ref={closeRef} type="button" className="stage-focus__close" onClick={onClose} aria-label="Close stage focus">
              <svg width="19" height="19" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <path d="M4.5 4.5 15.5 15.5M15.5 4.5 4.5 15.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              </svg>
            </button>
          </header>

          <div className="stage-focus__body">
            <div className={`stage-focus__architecture ${transitionScene ? "is-transitioning" : ""}`} aria-label="Live workflow architecture">
              <div className="focus-architecture__scenes">
                {transitionScene && previousNodeId && (
                  <div className="focus-architecture__scene is-outgoing" aria-hidden="true">
                    <FocusArchitecturePane
                      positions={positions}
                      nodeStatus={nodeStatus}
                      nodeElapsed={nodeElapsed}
                      selectedNodeId={previousNodeId}
                      reducedMotion={reducedMotion}
                      interactive={false}
                      onSelectNode={() => undefined}
                    />
                  </div>
                )}
                <div className={`focus-architecture__scene ${transitionScene ? "is-incoming" : "is-current"}`}>
                  <FocusArchitecturePane
                    positions={positions}
                    nodeStatus={nodeStatus}
                    nodeElapsed={nodeElapsed}
                    selectedNodeId={node.id}
                    reducedMotion={reducedMotion}
                    interactive={!transitionScene}
                    onSelectNode={onNavigate}
                  />
                </div>
              </div>
            </div>

            <div className={`stage-focus__details-layer ${transitionScene ? "is-transitioning" : ""}`} key={node.id}>
              <StageDetailScroller
                node={node}
                detail={detail}
                status={status}
                elapsedMs={elapsedMs}
                nextNode={nextNode}
                transitioning={transitionScene}
                onAdvance={() => nextId && onNavigate(nextId)}
                onActiveSectionChange={setActiveSection}
              />
            </div>
          </div>
        </div>
      </section>

      <div className="visually-hidden" aria-live="polite" aria-atomic="true">{announcement}</div>
    </div>
  );
}
