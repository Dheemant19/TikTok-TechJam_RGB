import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useTheme } from "../hooks/useTheme";
import { BENCHMARK_OPTIONS, useRunStore, type BenchmarkId } from "../liveworkflow/runStore";
import { selectBenchmark } from "../liveworkflow/selectors";
import { PRIMARY_ROUTES } from "../data/routeRegistry";


interface PillSpring {
  left: number;
  width: number;
  targetLeft: number;
  targetWidth: number;
  velocityLeft: number;
  velocityWidth: number;
  frame: number;
  lastTime: number;
  initialized: boolean;
}

interface TopToolbarProps {
  /** 0 = restrained glide, 1 = full elastic stretch. */
  pillFluidity?: number;
}

const PILL_SPRING = {
  stiffness: 450,
  mass: 0.8,
};

export function TopToolbar({ pillFluidity = 0.45 }: TopToolbarProps) {
  const isNarrow = useMediaQuery("(max-width: 720px)");
  const location = useLocation();
  const onLiveWorkflow = location.pathname === "/";
  const fluidity = Math.min(1, Math.max(0, pillFluidity));
  const pillMotionRef = useRef({
    damping: 48 - fluidity * 13,
    stretchFactor: 0.006 + fluidity * 0.019,
    maxStretch: 8 + fluidity * 20,
  });
  pillMotionRef.current = {
    damping: 48 - fluidity * 13,
    stretchFactor: 0.006 + fluidity * 0.019,
    maxStretch: 8 + fluidity * 20,
  };

  const navRef = useRef<HTMLElement>(null);
  const indicatorRef = useRef<HTMLSpanElement>(null);
  const linkRefs = useRef<Array<HTMLAnchorElement | null>>([]);
  const springRef = useRef<PillSpring>({
    left: 0,
    width: 0,
    targetLeft: 0,
    targetWidth: 0,
    velocityLeft: 0,
    velocityWidth: 0,
    frame: 0,
    lastTime: 0,
    initialized: false,
  });

  const activeIndex = PRIMARY_ROUTES.findIndex((destination) =>
    destination.to === "/" ? location.pathname === "/" : location.pathname.startsWith(destination.to)
  );

  useLayoutEffect(() => {
    const measure = () => {
      const indicator = indicatorRef.current;
      if (!indicator) return;
      if (activeIndex < 0) {
        indicator.style.opacity = "0";
        return;
      }
      const active = linkRefs.current[activeIndex];
      if (!active) return;
      indicator.style.opacity = "1";

      const spring = springRef.current;
      spring.targetLeft = active.offsetLeft;
      spring.targetWidth = active.offsetWidth;

      const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (!spring.initialized || reduceMotion) {
        if (spring.frame) cancelAnimationFrame(spring.frame);
        spring.left = spring.targetLeft;
        spring.width = spring.targetWidth;
        spring.velocityLeft = 0;
        spring.velocityWidth = 0;
        spring.frame = 0;
        spring.initialized = true;
        indicator.style.transform = `translate3d(${spring.left}px, 0, 0)`;
        indicator.style.width = `${spring.width}px`;
        return;
      }

      if (spring.frame) return;
      spring.lastTime = 0;

      const step = (time: number) => {
        const current = springRef.current;
        const element = indicatorRef.current;
        if (!element) {
          current.frame = 0;
          return;
        }
        if (!current.lastTime) {
          current.lastTime = time;
          current.frame = requestAnimationFrame(step);
          return;
        }

        const dt = Math.min((time - current.lastTime) / 1000, 1 / 30);
        current.lastTime = time;
        const motion = pillMotionRef.current;
        const accelerationLeft =
          (-PILL_SPRING.stiffness * (current.left - current.targetLeft) -
            motion.damping * current.velocityLeft) /
          PILL_SPRING.mass;
        const accelerationWidth =
          (-PILL_SPRING.stiffness * (current.width - current.targetWidth) -
            motion.damping * current.velocityWidth) /
          PILL_SPRING.mass;

        current.velocityLeft += accelerationLeft * dt;
        current.velocityWidth += accelerationWidth * dt;
        current.left += current.velocityLeft * dt;
        current.width += current.velocityWidth * dt;

        const stretch = Math.min(
          Math.abs(current.velocityLeft) * motion.stretchFactor,
          motion.maxStretch
        );
        const direction = Math.sign(current.velocityLeft);
        const visualLeft = current.left - stretch * (0.5 - direction * 0.05);
        const visualWidth = Math.max(1, current.width + stretch);
        element.style.transform = `translate3d(${visualLeft}px, 0, 0)`;
        element.style.width = `${visualWidth}px`;

        const settled =
          Math.abs(current.left - current.targetLeft) < 0.05 &&
          Math.abs(current.width - current.targetWidth) < 0.05 &&
          Math.abs(current.velocityLeft) < 0.05 &&
          Math.abs(current.velocityWidth) < 0.05;
        if (settled) {
          current.left = current.targetLeft;
          current.width = current.targetWidth;
          current.velocityLeft = 0;
          current.velocityWidth = 0;
          current.frame = 0;
          element.style.transform = `translate3d(${current.left}px, 0, 0)`;
          element.style.width = `${current.width}px`;
          return;
        }
        current.frame = requestAnimationFrame(step);
      };

      spring.frame = requestAnimationFrame(step);
    };

    measure();
    window.addEventListener("resize", measure);
    let cancelled = false;
    if (typeof document !== "undefined" && "fonts" in document) {
      document.fonts.ready.then(() => {
        if (!cancelled) measure();
      });
    }
    return () => {
      cancelled = true;
      window.removeEventListener("resize", measure);
    };
  }, [activeIndex, isNarrow]);

  useEffect(
    () => () => {
      if (springRef.current.frame) cancelAnimationFrame(springRef.current.frame);
    },
    []
  );

  return (
    <header className="top-toolbar">
      <div className="top-toolbar__brand">
        <div className="brand-mark" aria-hidden="true">
          <svg width="25" height="25" viewBox="0 0 25 25" fill="none">
            <path d="M5 7.5h6.5l3.1 4.7h5.4M5 17.5h6.5l3.1-5.3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="5" cy="7.5" r="2.2" fill="currentColor" />
            <circle cx="5" cy="17.5" r="2.2" fill="currentColor" />
            <circle cx="20" cy="12.2" r="2.2" fill="currentColor" />
          </svg>
        </div>
        {!isNarrow && (
          <div className="top-toolbar__brand-copy">
            <strong>FlowState</strong>
            <span>Workflow Observer</span>
          </div>
        )}
      </div>

      <nav ref={navRef} className="top-nav" aria-label="Primary navigation">
        <span ref={indicatorRef} className="top-nav__indicator" aria-hidden="true" />
        {PRIMARY_ROUTES.map((destination, index) => (
          <NavLink
            key={destination.to}
            ref={(element) => {
              linkRefs.current[index] = element;
            }}
            to={destination.to}
            end={destination.to === "/"}
            className={({ isActive }) => `top-nav__link ${isActive ? "is-active" : ""}`}
          >
            {isNarrow ? destination.shortLabel : destination.label}
          </NavLink>
        ))}
      </nav>

      <div className="top-toolbar__actions">
        <ThemeToggle />
        {!isNarrow && (
          <NavLink
            to="/autonomy"
            aria-label="Autonomy Log"
            className={({ isActive }) => `autonomy-link ${isActive ? "is-active" : ""}`}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 3" />
            </svg>
            <span>Autonomy Log</span>
          </NavLink>
        )}
        {onLiveWorkflow && !isNarrow && <RunControls />}
      </div>
    </header>
  );
}

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggleTheme}
      aria-pressed={isDark}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
    >
      {isDark ? (
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4.2" />
          <path d="M12 2.5v2.4M12 19.1v2.4M4.6 4.6l1.7 1.7M17.7 17.7l1.7 1.7M2.5 12h2.4M19.1 12h2.4M4.6 19.4l1.7-1.7M17.7 6.3l1.7-1.7" />
        </svg>
      ) : (
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />
        </svg>
      )}
    </button>
  );
}

const SESSION_STATUS_COLOR: Record<string, string> = {
  waiting: "var(--status-waiting)",
  ready: "var(--status-waiting)",
  running: "var(--status-running)",
  paused: "var(--status-attention)",
  succeeded: "var(--status-success)",
  failed: "var(--status-failed)",
  rejected: "var(--status-attention)",
  skipped: "var(--status-waiting)",
  blocked: "var(--status-failed)",
};

// A raw session_id (`session-20260901T101503482913Z-a1b2c3d4`) tells a user
// nothing at a glance -- the row must lead with when the session started,
// not its opaque identifier. The full id remains available as a tooltip for
// anyone who needs to correlate it with logs.
function formatSessionDate(createdAt: string): string {
  const created = new Date(createdAt);
  if (Number.isNaN(created.getTime())) return "Unknown start time";
  return created.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function SessionPicker() {
  const sessions = useRunStore((state) => state.sessions);
  const sessionId = useRunStore((state) => state.sessionId);
  const attach = useRunStore((state) => state.attach);
  const deleteSession = useRunStore((state) => state.deleteSession);
  const refreshSessions = useRunStore((state) => state.refreshSessions);
  const [deleting, setDeleting] = useState(false);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const activeSession = sessions.find((session) => session.session_id === sessionId);
  const status = activeSession?.status.toLowerCase();
  const canDelete = !!activeSession && !["ready", "running", "paused"].includes(status ?? "");

  // `deleteSession()` only cleared `deleting` on the catch branch -- on
  // success it always changes `sessionId` (deleting the attached session
  // detaches, per runStore.deleteSession), but the button itself never
  // unmounts, so the flag stayed stuck true forever after the first
  // successful delete, showing a permanent spinner on every session picked
  // afterward. Reset it whenever the attached session changes for any
  // reason, not only the one this component itself triggered.
  useEffect(() => {
    setDeleting(false);
  }, [sessionId]);

  // Closing on outside pointer activity and Escape matches native `<select>`
  // dismissal behavior without relying on any native dropdown chrome (whose
  // unstyleable Windows/Chromium focus ring was the "weird blue line").
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (sessions.length === 0) return null;
  return (
    <div className="session-control">
      <div className="session-picker" ref={rootRef}>
        <svg className="session-picker__icon" width="15" height="15" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <ellipse cx="10" cy="5" rx="5.8" ry="2.6" stroke="currentColor" strokeWidth="1.35" />
          <path d="M4.2 5v5c0 1.45 2.6 2.65 5.8 2.65s5.8-1.2 5.8-2.65V5M4.2 10v5c0 1.45 2.6 2.65 5.8 2.65s5.8-1.2 5.8-2.65v-5" stroke="currentColor" strokeWidth="1.35" />
        </svg>
        <button
          ref={triggerRef}
          type="button"
          className="session-picker__trigger"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label="Select session"
          title={activeSession ? activeSession.session_id : "Select a session to view"}
          onClick={() => {
            if (!open) void refreshSessions();
            setOpen((value) => !value);
          }}
        >
          {activeSession ? (
            <>
              <span className="session-picker__trigger-date">{formatSessionDate(activeSession.created_at)}</span>
              <span className="session-picker__trigger-status" style={{ color: SESSION_STATUS_COLOR[status ?? ""] ?? "var(--text-2)" }}>
                {activeSession.status.length ? activeSession.status[0].toUpperCase() + activeSession.status.slice(1) : activeSession.status}
              </span>
            </>
          ) : (
            <span className="session-picker__trigger-date">Select a session</span>
          )}
        </button>
        <svg className={`session-picker__chevron ${open ? "is-open" : ""}`} width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <path d="m3.5 5.25 3.5 3.5 3.5-3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {open && (
          <ul className="session-picker__menu" role="listbox" aria-label="Sessions">
            {sessions.map((session) => (
              <li key={session.session_id} role="none">
                <button
                  type="button"
                  role="option"
                  aria-selected={session.session_id === sessionId}
                  className={`session-picker__option ${session.session_id === sessionId ? "is-selected" : ""}`}
                  title={session.session_id}
                  onClick={() => {
                    setOpen(false);
                    if (session.session_id !== sessionId) void attach(session.session_id);
                  }}
                >
                  <span className="session-picker__option-date">{formatSessionDate(session.created_at)}</span>
                  <span className="session-picker__option-status" style={{ color: SESSION_STATUS_COLOR[session.status.toLowerCase()] ?? "var(--text-2)" }}>
                  {session.status.length ? session.status[0].toUpperCase() + session.status.slice(1) : session.status}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {canDelete && (
        <button
          type="button"
          className="session-delete"
          disabled={deleting}
          aria-label="Delete selected session"
          title="Delete selected session"
          onClick={async () => {
            const label = activeSession ? `the session from ${formatSessionDate(activeSession.created_at)}` : "this session";
            if (!window.confirm(`Delete ${label}? This removes its saved run history from this machine.`)) return;
            setDeleting(true);
            try {
              await deleteSession();
            } catch {
              setDeleting(false);
            }
          }}
        >
          {deleting ? <span className="toolbar-spinner" aria-hidden="true" /> : (
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
              <path d="M4 5.5h10M7 5.5V3.8c0-.5.4-.9.9-.9h2.2c.5 0 .9.4.9.9v1.7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M5.2 5.5 5.9 14.3a1 1 0 0 0 1 .9h4.2a1 1 0 0 0 1-.9l.7-8.8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M7.5 8v5M9 8v5M10.5 8v5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          )}
        </button>
      )}
    </div>
  );
}

function RunControls() {
  const sessionId = useRunStore((state) => state.sessionId);
  const phase = useRunStore((state) => state.phase);
  const snapshot = useRunStore((state) => state.snapshot);
  const error = useRunStore((state) => state.error);
  const events = useRunStore((state) => state.events);
  const selectedBenchmark = useRunStore((state) => state.selectedBenchmark);
  const setSelectedBenchmark = useRunStore((state) => state.setSelectedBenchmark);
  const startRun = useRunStore((state) => state.startRun);
  const pauseRun = useRunStore((state) => state.pauseRun);
  const resumeRun = useRunStore((state) => state.resumeRun);
  const cancelRun = useRunStore((state) => state.cancelRun);
  const detach = useRunStore((state) => state.detach);
  const refreshSessions = useRunStore((state) => state.refreshSessions);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

  const isConnecting = phase === "connecting";
  const allowed = snapshot?.allowed_actions ?? [];
  const label = isConnecting ? "Starting..." : "Start Run";
  const activeBenchmark = selectBenchmark(events);

  if (!sessionId) {
    return (
      <div className="run-controls">
        {error && (
          <span className="mono" style={{ fontSize: 11, color: "var(--status-attention)", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={error}>
            {error}
          </span>
        )}
        <label className="benchmark-picker">
          <select
            aria-label="Training dataset"
            value={selectedBenchmark}
            onChange={(event) => setSelectedBenchmark(event.target.value as BenchmarkId)}
            disabled={isConnecting}
          >
            {BENCHMARK_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>{option.label}</option>
            ))}
          </select>
        </label>
        <SessionPicker />
        <button type="button" onClick={() => void startRun()} disabled={isConnecting} className="toolbar-button toolbar-button--run">
          {isConnecting ? <span className="toolbar-spinner" aria-hidden="true" /> : (
            <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="m5.25 3.5 6 4.5-6 4.5v-9Z" fill="currentColor" />
            </svg>
          )}
          {label}
        </button>
      </div>
    );
  }

  return (
    <div className="run-controls">
      <span className="connection-chip" data-phase={phase} title={error ?? undefined}>
        <svg className="connection-chip__glyph" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M2.5 8h2l1.35-3.1L8.1 11l1.6-4h3.8" stroke="currentColor" strokeWidth="1.45" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span>{phase === "live" ? "Live" : phase === "retrying" ? "Reconnecting" : phase === "connecting" ? "Connecting" : phase}</span>
      </span>
      {activeBenchmark && (
        <span className="benchmark-chip" title={`Training dataset: ${activeBenchmark.label}`}>
          {activeBenchmark.label}
        </span>
      )}
      <SessionPicker />
      <button type="button" onClick={() => void detach()} className="toolbar-icon-action" aria-label="Detach from session" title="Detach from session">
        <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M8.1 5.2H5.4A1.4 1.4 0 0 0 4 6.6v6.8a1.4 1.4 0 0 0 1.4 1.4h2.7M12.2 6.5 15.7 10l-3.5 3.5M7.1 10h8.2" stroke="currentColor" strokeWidth="1.45" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {allowed.includes("pause") && (
        <button type="button" onClick={() => void pauseRun()} className="toolbar-button toolbar-button--quiet">Pause</button>
      )}
      {allowed.includes("resume") && (
        <button type="button" onClick={() => void resumeRun()} className="toolbar-button toolbar-button--run">Resume</button>
      )}
      {allowed.includes("cancel") && (
        <button
          type="button"
          onClick={() => {
            if (window.confirm("Cancel this run? History is preserved and the stable fallback remains available.")) void cancelRun();
          }}
          className="toolbar-button toolbar-button--quiet"
        >
          Cancel
        </button>
      )}
    </div>
  );
}
