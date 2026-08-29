import { useEffect, useLayoutEffect, useRef } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useTheme } from "../hooks/useTheme";
import { useRunStore } from "../liveworkflow/runStore";

const DESTINATIONS = [
  { to: "/", label: "Live Workflow" },
  { to: "/data-profile", label: "Data Profile" },
  { to: "/experiments", label: "Experiments" },
  { to: "/research", label: "Research Library" },
  { to: "/resources", label: "Resources" },
  { to: "/package", label: "Final Package" },
];

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

  const activeIndex = DESTINATIONS.findIndex((destination) =>
    destination.to === "/" ? location.pathname === "/" : location.pathname.startsWith(destination.to)
  );

  useLayoutEffect(() => {
    const measure = () => {
      const active = linkRefs.current[activeIndex];
      const indicator = indicatorRef.current;
      if (!active || !indicator) return;

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
            <strong>RIGOR-RS</strong>
            <span>Workflow Observer</span>
          </div>
        )}
      </div>

      <nav ref={navRef} className="top-nav" aria-label="Primary navigation">
        <span ref={indicatorRef} className="top-nav__indicator" aria-hidden="true" />
        {DESTINATIONS.map((destination, index) => (
          <NavLink
            key={destination.to}
            ref={(element) => {
              linkRefs.current[index] = element;
            }}
            to={destination.to}
            end={destination.to === "/"}
            className={({ isActive }) => `top-nav__link ${isActive ? "is-active" : ""}`}
          >
            {isNarrow ? destination.label.split(" ")[0] : destination.label}
          </NavLink>
        ))}
      </nav>

      <div className="top-toolbar__actions">
        <ThemeToggle />
        {!isNarrow && (
          <NavLink
            to="/autonomy"
            className={({ isActive }) => `autonomy-link ${isActive ? "is-active" : ""}`}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 3" />
            </svg>
            Autonomy Log
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

function SessionPicker() {
  const sessions = useRunStore((state) => state.sessions);
  const sessionId = useRunStore((state) => state.sessionId);
  const attach = useRunStore((state) => state.attach);
  const refreshSessions = useRunStore((state) => state.refreshSessions);

  if (sessions.length === 0) return null;
  return (
    <select
      className="toolbar-button toolbar-button--quiet"
      value={sessionId ?? ""}
      onMouseDown={() => void refreshSessions()}
      onChange={(event) => {
        if (event.target.value) void attach(event.target.value);
      }}
      aria-label="Select session"
      title="Select a session to view"
    >
      <option value="" disabled>
        Sessions...
      </option>
      {sessions.map((session) => (
        <option key={session.session_id} value={session.session_id}>
          {session.session_id.slice(0, 24)} - {session.status}
        </option>
      ))}
    </select>
  );
}

function RunControls() {
  const sessionId = useRunStore((state) => state.sessionId);
  const phase = useRunStore((state) => state.phase);
  const snapshot = useRunStore((state) => state.snapshot);
  const error = useRunStore((state) => state.error);
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

  if (!sessionId) {
    return (
      <div className="run-controls">
        {error && (
          <span className="mono" style={{ fontSize: 11, color: "var(--status-attention)", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={error}>
            {error}
          </span>
        )}
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
      <span className="mono tabular" style={{ fontSize: 11, color: "var(--text-2)" }} title={sessionId}>
        {phase === "live" ? "Live" : phase === "retrying" ? "Reconnecting..." : phase} - {sessionId.slice(0, 24)}
      </span>
      <SessionPicker />
      <button type="button" onClick={() => void detach()} className="toolbar-button toolbar-button--quiet">
        Detach
      </button>
      {allowed.includes("pause") && (
        <button type="button" onClick={() => void pauseRun()} className="toolbar-button toolbar-button--quiet">
          Pause
        </button>
      )}
      {allowed.includes("resume") && (
        <button type="button" onClick={() => void resumeRun()} className="toolbar-button toolbar-button--run">
          Resume
        </button>
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
