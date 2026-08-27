import { PlayCircle, History, Sparkles } from "lucide-react";
import { useSessionList, useStartSession } from "@/api/queries";
import styles from "./SessionBar.module.css";

export type ViewMode = "live" | "replay" | "demo";

interface SessionBarProps {
  sessionId: string | null;
  mode: ViewMode;
  onSessionChange: (sessionId: string | null) => void;
  onModeChange: (mode: ViewMode) => void;
}

const CHALLENGE_CONFIG_PATH = "configs/challenge/kuairand_pure.yaml";
const BUDGET_CONFIG_PATH = "configs/budgets/competition.yaml";

export function SessionBar({ sessionId, mode, onSessionChange, onModeChange }: SessionBarProps) {
  const { data: sessions } = useSessionList();
  const startSession = useStartSession();

  function handleStart() {
    startSession.mutate(
      { challenge_config_path: CHALLENGE_CONFIG_PATH, budget_config_path: BUDGET_CONFIG_PATH },
      {
        onSuccess: (response) => {
          onSessionChange(response.session_id);
          onModeChange("live");
        },
      },
    );
  }

  return (
    <div className={styles.bar}>
      <label className={styles.field}>
        <span className="text-small">Session</span>
        <select
          value={sessionId ?? ""}
          onChange={(event) => {
            onSessionChange(event.target.value || null);
            onModeChange("live");
          }}
        >
          <option value="">No session selected</option>
          {sessions?.map((session) => (
            <option key={session.session_id} value={session.session_id}>
              {session.session_id} — {session.status}
              {session.finalized ? " (finalized)" : ""}
            </option>
          ))}
        </select>
      </label>

      <button type="button" className="pressable" onClick={handleStart} disabled={startSession.isPending}>
        {startSession.isPending ? "Starting…" : "New session"}
      </button>

      <div className={styles.modeGroup} role="group" aria-label="View mode">
        <button type="button" className={styles.modeButton} data-active={mode === "live" || undefined} onClick={() => onModeChange("live")}>
          <PlayCircle size={14} aria-hidden="true" /> Live
        </button>
        <button
          type="button"
          className={styles.modeButton}
          data-active={mode === "replay" || undefined}
          disabled={!sessionId}
          onClick={() => onModeChange("replay")}
        >
          <History size={14} aria-hidden="true" /> Replay
        </button>
        <button type="button" className={styles.modeButton} data-active={mode === "demo" || undefined} onClick={() => onModeChange("demo")}>
          <Sparkles size={14} aria-hidden="true" /> Demo data
        </button>
      </div>
    </div>
  );
}
