import { NavLink, useLocation } from "react-router-dom";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useRunStore } from "../liveworkflow/runStore";

const DESTINATIONS = [
  { to: "/", label: "Live Workflow" },
  { to: "/data-profile", label: "Data Profile" },
  { to: "/experiments", label: "Experiments" },
  { to: "/research", label: "Research Library" },
  { to: "/resources", label: "Resources" },
  { to: "/package", label: "Final Package" },
];

export function TopToolbar() {
  const isNarrow = useMediaQuery("(max-width: 720px)");
  const location = useLocation();
  const onLiveWorkflow = location.pathname === "/";

  return (
    <header
      style={{
        position: "relative",
        display: "flex",
        alignItems: "center",
        gap: "var(--space-4)",
        height: 68,
        padding: `0 ${isNarrow ? "16px" : "22px"}`,
        background: "rgba(255,255,255,.78)",
        backdropFilter: "blur(14px)",
        borderBottom: "1px solid rgba(15,23,42,.07)",
        zIndex: 50,
        flexShrink: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
        <div
          style={{
            width: 34,
            height: 34,
            borderRadius: 10,
            background: "linear-gradient(135deg,#60a5fa,#3b82f6)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: "0 6px 16px -4px rgba(59,130,246,.6)",
          }}
        >
          <span style={{ color: "#fff", fontWeight: 800, fontSize: 15 }}>R</span>
        </div>
        {!isNarrow && (
          <div>
            <div style={{ fontWeight: 800, fontSize: 15, color: "#0f172a", letterSpacing: "-.01em" }}>RIGOR-RS</div>
            <div style={{ fontSize: 11, color: "#94a3b8", fontWeight: 600 }}>Workflow Observer</div>
          </div>
        )}
      </div>

      <nav style={{ display: "flex", gap: 4, flex: 1, minWidth: 0, overflowX: "auto", scrollbarWidth: "none" }}>
        {DESTINATIONS.map((d) => (
          <NavLink
            key={d.to}
            to={d.to}
            end={d.to === "/"}
            style={({ isActive }) => ({
              padding: "8px 12px",
              borderRadius: 10,
              fontSize: 13,
              fontWeight: 700,
              flexShrink: 0,
              whiteSpace: "nowrap",
              color: isActive ? "#fff" : "#475569",
              background: isActive ? "#3b82f6" : "transparent",
              transition: "background .15s ease",
            })}
          >
            {isNarrow ? d.label.split(" ")[0] : d.label}
          </NavLink>
        ))}
      </nav>

      <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        {!isNarrow && (
          <NavLink
            to="/autonomy"
            style={({ isActive }) => ({
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "9px 14px",
              borderRadius: 12,
              border: "1px solid rgba(15,23,42,.08)",
              background: isActive ? "var(--primary-tint, #eff6ff)" : "#fff",
              color: isActive ? "#2563eb" : "#475569",
              fontWeight: 700,
              fontSize: 13,
            })}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 3" />
            </svg>
            Autonomy Log
          </NavLink>
        )}
        {onLiveWorkflow && !isNarrow && <RunControls isNarrow={isNarrow} />}
      </div>
    </header>
  );
}

function RunControls({ isNarrow }: { isNarrow: boolean }) {
  const runStatus = useRunStore((s) => s.runStatus);
  const start = useRunStore((s) => s.start);
  const reset = useRunStore((s) => s.reset);
  const isRunning = runStatus === "running";
  const label = isRunning ? "Running…" : runStatus === "done" ? "Run Again" : "Run Workflow";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
      {!isNarrow && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "8px 14px",
            borderRadius: 12,
            background: "#fff",
            border: "1px solid rgba(15,23,42,.08)",
            fontSize: 13,
            color: "#475569",
            fontWeight: 600,
            boxShadow: "0 1px 2px rgba(15,23,42,.04)",
          }}
        >
          Environment: <span style={{ color: "#0f172a", fontWeight: 700 }}>Production</span>
        </div>
      )}
      <button
        onClick={reset}
        style={{
          padding: "10px 16px",
          borderRadius: 12,
          border: "1px solid rgba(15,23,42,.08)",
          background: "#fff",
          color: "#475569",
          fontWeight: 700,
          fontSize: 13,
          cursor: "pointer",
        }}
      >
        Reset
      </button>
      <button
        onClick={start}
        disabled={isRunning}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "10px 18px",
          borderRadius: 12,
          border: "none",
          background: isRunning ? "linear-gradient(135deg,#93c5fd,#60a5fa)" : "linear-gradient(135deg,#60a5fa,#2563eb)",
          color: "#fff",
          fontWeight: 800,
          fontSize: 13,
          cursor: isRunning ? "default" : "pointer",
          boxShadow: "0 10px 24px -8px rgba(37,99,235,.6)",
        }}
      >
        {isRunning && (
          <span
            aria-hidden
            style={{
              width: 13,
              height: 13,
              borderRadius: "50%",
              border: "2px solid rgba(255,255,255,.5)",
              borderTopColor: "#fff",
              animation: "spin .7s linear infinite",
            }}
          />
        )}
        {label}
      </button>
    </div>
  );
}
