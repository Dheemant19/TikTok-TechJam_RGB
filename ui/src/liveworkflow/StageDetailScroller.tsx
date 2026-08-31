import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, type CSSProperties } from "react";
import type { NodeDef, NodeStatus } from "../data/nodeRegistry";
import { GROUP_LABELS } from "../data/nodeRegistry";
import { laneColorFor, type FieldRow, type HistoryRow, type NodeDetail } from "./laneData";
import { statusMeta } from "./NodeCard";
import { stageProgressLabel, type DetailSectionId } from "./stageNavigation";

const REDACTED_VALUE = "Hidden to protect data and credentials";

/** Imperative handle exposed to `StageFocusView` so the vertical section
 * rail (AGENTS.md #2) can drive the scroller without a second source of
 * scroll-position truth -- the `IntersectionObserver` below remains the
 * only thing that reports the active section back up. */
export interface StageDetailScrollerHandle {
  scrollToSection: (id: DetailSectionId) => void;
}

interface Props {
  node: NodeDef;
  detail: NodeDetail;
  status: NodeStatus;
  elapsedMs: number;
  nextNode: NodeDef | null;
  transitioning: boolean;
  reducedMotion: boolean;
  onAdvance: () => void;
  onActiveSectionChange: (section: DetailSectionId) => void;
}

function isRedacted(value: string): boolean {
  return value === REDACTED_VALUE;
}

function isTechnical(row: FieldRow): boolean {
  return row.mono || /(?:\.json|hash|GAUC|nDCG|primary|train:|val:|test:)/i.test(row.value);
}

function DetailValue({ row, className }: { row: FieldRow; className?: string }) {
  if (isRedacted(row.value)) {
    return (
      <dd className={`stage-detail__value stage-detail__value--redacted ${className ?? ""}`}>
        <span className="stage-detail__redaction-mark" aria-hidden="true">••••••••</span>
        <span>Hidden to protect data and credentials</span>
      </dd>
    );
  }
  return <dd className={`stage-detail__value ${isTechnical(row) ? "mono" : ""} ${className ?? ""}`}>{row.value}</dd>;
}

function StatusReadout({ status, isRecovery, elapsedMs }: { status: NodeStatus; isRecovery?: boolean; elapsedMs: number }) {
  const meta = statusMeta(status, isRecovery);
  return (
    <span className="stage-detail__status" style={{ color: meta.color }}>
      <span className="stage-detail__status-dot" style={{ background: meta.dot }} aria-hidden="true" />
      {meta.text}
      {status === "running" && <span className="mono tabular">{(elapsedMs / 1000).toFixed(1)}s</span>}
    </span>
  );
}

function HistoryEntry({ entry }: { entry: HistoryRow }) {
  return (
    <li className="stage-detail__history-entry">
      <span className="stage-detail__history-dot" style={{ background: entry.dotColor }} aria-hidden="true" />
      <div>
        <div className="stage-detail__history-title">
          <strong>Attempt {entry.attempt}</strong>
          <span>{entry.status}</span>
        </div>
        <p>
          <span className="mono tabular">{entry.time}</span>
          <span className="stage-detail__history-separator" aria-hidden="true">/</span>
          {entry.note}
        </p>
      </div>
    </li>
  );
}

export const StageDetailScroller = forwardRef<StageDetailScrollerHandle, Props>(function StageDetailScroller({
  node,
  detail,
  status,
  elapsedMs,
  nextNode,
  transitioning,
  reducedMotion,
  onAdvance,
  onActiveSectionChange,
}, ref) {
  const colors = laneColorFor(node);
  const scrollRef = useRef<HTMLDivElement>(null);
  const advanceLockRef = useRef(false);
  const lastTouchYRef = useRef<number | null>(null);

  const requestAdvance = useCallback(() => {
    if (!nextNode || transitioning || advanceLockRef.current) return;
    advanceLockRef.current = true;
    onAdvance();
  }, [nextNode, onAdvance, transitioning]);

  useEffect(() => {
    advanceLockRef.current = false;
    const root = scrollRef.current;
    if (root) root.scrollTop = 0;
    onActiveSectionChange("summary");
  }, [node.id, onActiveSectionChange]);

  // Smooth-scrolls (or instant-jumps, under reduced motion) the scroller to
  // the requested section -- the single entry point the vertical rail in
  // `StageFocusView` uses to drive this component. A programmatic scroll
  // still fires the `IntersectionObserver` below mid-flight (and, for short
  // sections that don't fill the viewport, can settle on a *different*
  // section than the one just requested -- e.g. clicking "History" while
  // "Output" is still nominally more visible by intersection ratio), which
  // would silently overwrite the user's explicit click. `suppressObserverUntilRef`
  // gives the requested section a brief grace window to win outright; manual
  // scrolling still drives the active section immediately afterward.
  const suppressObserverUntilRef = useRef(0);
  const sectionVisibilityRef = useRef(new Map<Element, boolean>());
  const scrollToSection = useCallback((id: DetailSectionId) => {
    const root = scrollRef.current;
    const target = root?.querySelector<HTMLElement>(`[data-section="${id}"]`);
    suppressObserverUntilRef.current = Date.now() + 600;
    target?.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
  }, [reducedMotion]);

  useImperativeHandle(ref, () => ({ scrollToSection }), [scrollToSection]);

  useEffect(() => {
    const root = scrollRef.current;
    if (!root || typeof IntersectionObserver === "undefined") return;
    const sections = Array.from(root.querySelectorAll<HTMLElement>("[data-section]"));
    sectionVisibilityRef.current.clear();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          sectionVisibilityRef.current.set(entry.target, entry.isIntersecting);
        }
        if (Date.now() < suppressObserverUntilRef.current) return;
        // IntersectionObserver only reports targets whose state changed in
        // the current callback. Keep visibility for every section so a short
        // trailing section can still win after an earlier section changes.
        const lastVisible = [...sections]
          .reverse()
          .find((candidate) => sectionVisibilityRef.current.get(candidate));
        const section = lastVisible?.dataset.section as DetailSectionId | undefined;
        if (section) onActiveSectionChange(section);
      },
      { root, rootMargin: "-8% 0px -58% 0px", threshold: [0.05, 0.2, 0.4, 0.7, 1] },
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, [node.id, onActiveSectionChange]);

  useEffect(() => {
    const root = scrollRef.current;
    if (!root) return;
    const atBottom = () => root.scrollTop + root.clientHeight >= root.scrollHeight - 4;
    const onWheel = (event: WheelEvent) => {
      if (event.deltaY <= 0 || !atBottom()) return;
      event.preventDefault();
      event.stopPropagation();
      requestAdvance();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const continuesDown = event.key === "ArrowDown" || event.key === "PageDown" || event.key === " ";
      if (!continuesDown || !atBottom()) return;
      event.preventDefault();
      event.stopPropagation();
      requestAdvance();
    };
    const onTouchStart = (event: TouchEvent) => {
      lastTouchYRef.current = event.touches[0]?.clientY ?? null;
    };
    const onTouchMove = (event: TouchEvent) => {
      const currentY = event.touches[0]?.clientY;
      const previousY = lastTouchYRef.current;
      if (currentY === undefined || previousY === null) return;
      const continuesDown = previousY - currentY > 2;
      lastTouchYRef.current = currentY;
      if (!continuesDown || !atBottom()) return;
      event.preventDefault();
      event.stopPropagation();
      requestAdvance();
    };
    root.addEventListener("wheel", onWheel, { passive: false });
    root.addEventListener("keydown", onKeyDown);
    root.addEventListener("touchstart", onTouchStart, { passive: true });
    root.addEventListener("touchmove", onTouchMove, { passive: false });
    return () => {
      root.removeEventListener("wheel", onWheel);
      root.removeEventListener("keydown", onKeyDown);
      root.removeEventListener("touchstart", onTouchStart);
      root.removeEventListener("touchmove", onTouchMove);
    };
  }, [requestAdvance]);

  return (
    <div
      ref={scrollRef}
      className={`stage-detail-scroller ${transitioning ? "is-locked" : ""}`}
      role="region"
      aria-label={`Scrollable evidence for ${node.label}`}
      tabIndex={0}
      style={{ "--detail-accent": colors.b, "--detail-accent-soft": colors.a } as CSSProperties}
    >
      <section id="summary" data-section="summary" className="stage-detail__section stage-detail__section--summary" aria-labelledby="summary-heading">
        <div className="stage-detail__section-heading">
          <span className="stage-detail__section-marker" aria-hidden="true" />
          <div>
            <p className="stage-detail__section-kicker">Stage evidence</p>
            <h2 id="summary-heading">Summary</h2>
          </div>
        </div>
        <div className="stage-detail__summary-intro">
          <div>
            <p className="stage-detail__process-label">{node.label}</p>
            <p className="stage-detail__summary-copy">{detail.summary}</p>
          </div>
          <StatusReadout status={status} isRecovery={node.isRecovery} elapsedMs={elapsedMs} />
        </div>
        <dl className="stage-detail__metadata">
          <div>
            <dt>Lane</dt>
            <dd>{GROUP_LABELS[node.group]}</dd>
          </div>
          <div>
            <dt>Architecture</dt>
            <dd>{node.archLabel}</dd>
          </div>
          <div>
            <dt>Progress</dt>
            <dd className="mono">{stageProgressLabel(node.id)}</dd>
          </div>
        </dl>
        <div className="stage-detail__facts" aria-label="Stage facts">
          {detail.facts.map((fact) => (
            <div key={fact.label} className="stage-detail__fact">
              <span>{fact.label}</span>
              <strong>{fact.value}</strong>
            </div>
          ))}
        </div>
        <div className="stage-detail__latest-output">
          <div className="stage-detail__latest-output-heading">
            <span className="stage-detail__output-mark" aria-hidden="true" />
            <div>
              <h3>Latest output</h3>
              <p>The evidence recorded for the next stage.</p>
            </div>
          </div>
          <dl>
            {detail.output.slice(0, 2).map((row) => (
              <div key={row.label}>
                <dt>{row.label}</dt>
                <DetailValue row={row} />
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section id="input" data-section="input" className="stage-detail__section" aria-labelledby="input-heading">
        <div className="stage-detail__section-heading">
          <span className="stage-detail__section-marker" aria-hidden="true" />
          <div>
            <p className="stage-detail__section-kicker">Allowed reads</p>
            <h2 id="input-heading">Input</h2>
          </div>
        </div>
        <p className="stage-detail__section-copy">The material this stage is allowed to read before it begins.</p>
        <dl className="stage-detail__rows">
          {detail.input.map((row) => (
            <div key={row.label}>
              <dt>{row.label}</dt>
              <DetailValue row={row} />
            </div>
          ))}
        </dl>
      </section>

      <section id="output" data-section="output" className="stage-detail__section" aria-labelledby="output-heading">
        <div className="stage-detail__section-heading">
          <span className="stage-detail__section-marker" aria-hidden="true" />
          <div>
            <p className="stage-detail__section-kicker">Recorded handoff</p>
            <h2 id="output-heading">Output</h2>
          </div>
        </div>
        <p className="stage-detail__section-copy">The structured result written by this stage and handed to the next one.</p>
        <div className="stage-detail__output-list">
          <dl>
            {detail.output.map((row) => (
              <div key={row.label} className="stage-detail__output-row">
                <span className="stage-detail__output-row-marker" aria-hidden="true" />
                <div>
                  <dt>{row.label}</dt>
                  <DetailValue row={row} />
                </div>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section id="history" data-section="history" className="stage-detail__section stage-detail__section--history" aria-labelledby="history-heading">
        <div className="stage-detail__section-heading">
          <span className="stage-detail__section-marker" aria-hidden="true" />
          <div>
            <p className="stage-detail__section-kicker">Append-only record</p>
            <h2 id="history-heading">History</h2>
          </div>
        </div>
        <p className="stage-detail__section-copy">Attempts and recovery notes stay attached to the stage for replay and audit.</p>
        <ol className="stage-detail__history">
          {detail.history.map((entry) => <HistoryEntry key={`${entry.attempt}-${entry.time}-${entry.status}`} entry={entry} />)}
        </ol>
        <div className="stage-detail__continuation">
          {nextNode ? (
            <button type="button" onClick={requestAdvance} disabled={transitioning} className="stage-detail__continue">
              <span>
                <small>Continue to</small>
                <strong>{nextNode.label}</strong>
              </span>
              <svg width="19" height="19" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <path d="M3.5 10h12M10.5 5l5 5-5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          ) : (
            <div className="stage-detail__workflow-end">
              <span className="stage-detail__output-mark" aria-hidden="true" />
              <div>
                <small>Final stage</small>
                <strong>End of workflow</strong>
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
});
