import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { NODES, type NodeStatus } from "../data/nodeRegistry";
import { laneColorFor, NODE_DETAILS } from "./laneData";
import { FocusArchitecturePane } from "./FocusArchitecturePane";
import { StageDetailScroller, type StageDetailScrollerHandle } from "./StageDetailScroller";
import { statusMeta } from "./NodeCard";
import { buildNodeDetail } from "./nodeDetail";
import { useRunStore } from "./runStore";
import { selectLatestWatchdogDecision } from "./selectors";
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
  const scrollerRef = useRef<StageDetailScrollerHandle>(null);
  const sectionButtonRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [activeSection, setActiveSection] = useState<DetailSectionId>("summary");

  // Keep hooks mounted while the closing animation clears the selected id.
  // The fallback also keeps hook order stable when the component is mounted before opening.
  const node = nodeForId(nodeId) ?? NODES[0];
  const nodeStates = useRunStore((state) => state.nodeStates);
  const events = useRunStore((state) => state.events);
  const detail = useMemo(() => buildNodeDetail(node, nodeStates, NODE_DETAILS[node.id]), [node, nodeStates]);

  // Branch-aware "Continue to": a rejected watchdog decision loops back into
  // another research cycle instead of continuing to Save Run Evidence
  // (AGENTS.md #5) -- this only changes what the UI points at next, never
  // backend routing.
  const watchdogDecision = useMemo(() => selectLatestWatchdogDecision(events), [events]);
  const nextId = nextStageId(node.id, watchdogDecision);
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
    }, reducedMotion ? 0 : 1160);
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

  // A process-card transition owns the scroll/section state race (the
  // detail scroller resets to "summary" on every node change); disable the
  // rail for that brief window and re-enable it once the incoming detail
  // view is open, mirroring `isAdvancing` in useFlipInspector.
  const railDisabled = phase === "transitioning";

  const handleSelectSection = (id: DetailSectionId) => {
    if (railDisabled) return;
    scrollerRef.current?.scrollToSection(id);
    setActiveSection(id);
  };

  const focusSectionButton = (id: DetailSectionId) => {
    const index = DETAIL_SECTIONS.findIndex((section) => section.id === id);
    sectionButtonRefs.current[index]?.focus();
  };

  // ArrowUp/ArrowDown/Home/End move focus and selection through the four
  // sections regardless of which button in the row currently has focus.
  // Escape is intentionally left unhandled here so it keeps bubbling to the
  // root `onKeyDown` above, which still closes the whole stage view.
  const handleRailKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (railDisabled) return;
    const { key } = event;
    if (key !== "ArrowUp" && key !== "ArrowDown" && key !== "Home" && key !== "End") return;
    const row = (event.target as HTMLElement).closest<HTMLElement>("[data-rail-row]");
    const currentId = (row?.dataset.railRow as DetailSectionId | undefined) ?? activeSection;
    const currentIndex = DETAIL_SECTIONS.findIndex((section) => section.id === currentId);
    const fromIndex = currentIndex < 0 ? 0 : currentIndex;
    let nextIndex = fromIndex;
    if (key === "ArrowDown") nextIndex = Math.min(DETAIL_SECTIONS.length - 1, fromIndex + 1);
    else if (key === "ArrowUp") nextIndex = Math.max(0, fromIndex - 1);
    else if (key === "Home") nextIndex = 0;
    else nextIndex = DETAIL_SECTIONS.length - 1; // End
    event.preventDefault();
    const nextSectionId = DETAIL_SECTIONS[nextIndex].id;
    handleSelectSection(nextSectionId);
    focusSectionButton(nextSectionId);
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
            <div key={node.id} className={`stage-focus__header-copy ${transitionScene ? "is-transitioning" : ""}`}>
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
            <button ref={closeRef} type="button" className="stage-focus__close" onClick={onClose} aria-label="Close stage focus">
              <svg width="19" height="19" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <path d="M4.5 4.5 15.5 15.5M15.5 4.5 4.5 15.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              </svg>
            </button>
          </header>

          <div className="stage-focus__body">
            <div className={`stage-focus__architecture ${transitionScene ? "is-transitioning" : ""}`} aria-label="Live workflow architecture">
              <div className="focus-architecture__scenes">
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
              <div className={`stage-focus__details-column ${isNarrow ? "is-narrow" : ""}`}>
                <StageDetailScroller
                  ref={scrollerRef}
                  node={node}
                  detail={detail}
                  status={status}
                  elapsedMs={elapsedMs}
                  nextNode={nextNode}
                  transitioning={transitionScene}
                  reducedMotion={reducedMotion}
                  onAdvance={() => nextId && onNavigate(nextId)}
                  onActiveSectionChange={setActiveSection}
                />

                <nav
                  className={`stage-focus__section-nav ${isNarrow ? "is-narrow" : ""} ${railDisabled ? "is-disabled" : ""}`}
                  aria-label="Stage detail sections"
                  onKeyDown={handleRailKeyDown}
                >
                  {DETAIL_SECTIONS.map((section, index) => {
                    const isActive = activeSection === section.id;
                    return (
                      <div className="stage-focus__section-nav-row" data-rail-row={section.id} key={section.id}>
                        <button
                          type="button"
                          ref={(element) => {
                            sectionButtonRefs.current[index] = element;
                          }}
                          className="stage-focus__section-nav-label"
                          onClick={() => handleSelectSection(section.id)}
                          disabled={railDisabled}
                          aria-current={isActive ? "location" : undefined}
                        >
                          <span>{section.label}</span>
                        </button>
                      </div>
                    );
                  })}
                </nav>
              </div>
            </div>
          </div>
        </div>
      </section>

      <div className="visually-hidden" aria-live="polite" aria-atomic="true">{announcement}</div>
    </div>
  );
}
