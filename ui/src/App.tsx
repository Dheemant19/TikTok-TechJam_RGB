import { useState, type CSSProperties } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TopToolbar } from "@/components/TopToolbar";
import { SessionBar, type ViewMode } from "@/components/SessionBar";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { DemoBanner } from "@/components/DemoBanner";
import { LiveWorkflow } from "@/routes/LiveWorkflow";
import { DataProfile } from "@/routes/DataProfile";
import { Experiments } from "@/routes/Experiments";
import { ResearchLibrary } from "@/routes/ResearchLibrary";
import { Resources } from "@/routes/Resources";
import { FinalPackage } from "@/routes/FinalPackage";
import { useEventStream } from "@/api/useEventStream";
import { useReplay, useSnapshot } from "@/api/queries";
import { DEMO_EVENTS, DEMO_SNAPSHOT } from "@/fixtures/demoEvents";
import type { RunEvent, SessionSnapshot } from "@/api/types";

const queryClient = new QueryClient();
const REPLAY_SPEEDS = [0.5, 1, 2, 4] as const;
type ReplaySpeed = (typeof REPLAY_SPEEDS)[number];

function AppShell() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [mode, setMode] = useState<ViewMode>("live");
  const [replayIndex, setReplayIndex] = useState(0);
  const [replayPlaying, setReplayPlaying] = useState(false);
  const [replaySpeed, setReplaySpeed] = useState<ReplaySpeed>(1);

  const live = useEventStream(sessionId, mode === "live");
  const replay = useReplay(sessionId, mode === "replay");
  const liveSnapshot = useSnapshot(mode === "live" ? sessionId : null);

  const replayEvents: RunEvent[] = replay.data?.events.slice(0, replayIndex + 1) ?? [];
  const events: RunEvent[] = mode === "demo" ? DEMO_EVENTS : mode === "replay" ? replayEvents : live.events;
  const snapshot: SessionSnapshot | null =
    mode === "demo" ? DEMO_SNAPSHOT : mode === "replay" ? (replay.data?.final_snapshot ?? null) : (liveSnapshot.data ?? null);

  function handleSessionChange(next: string | null) {
    setSessionId(next);
    setReplayIndex(0);
    setReplayPlaying(false);
  }

  function handleModeChange(next: ViewMode) {
    setMode(next);
    if (next === "replay") setReplayIndex(0);
  }

  return (
    <BrowserRouter>
      <div style={{ "--header-height": mode === "demo" ? "7.25rem" : "6.25rem" } as CSSProperties}>
        <TopToolbar sessionId={mode === "live" ? sessionId : null} />
        <SessionBar sessionId={sessionId} mode={mode} onSessionChange={handleSessionChange} onModeChange={handleModeChange} />
        <ConnectionBanner connection={mode === "live" ? live.connection : "connected"} />
        {mode === "demo" && <DemoBanner />}
        <Routes>
          <Route
            path="/"
            element={
              <LiveWorkflow
                events={events}
                isReplay={mode === "replay"}
                replayTotal={replay.data?.events.length ?? 0}
                replayIndex={replayIndex}
                onReplayIndexChange={setReplayIndex}
                replayPlaying={replayPlaying}
                onReplayPlayingChange={setReplayPlaying}
                replaySpeed={replaySpeed}
                onReplaySpeedChange={setReplaySpeed}
              />
            }
          />
          <Route path="/data-profile" element={<DataProfile events={events} />} />
          <Route path="/experiments" element={<Experiments events={events} snapshot={snapshot} />} />
          <Route path="/research-library" element={<ResearchLibrary events={events} />} />
          <Route path="/resources" element={<Resources events={events} />} />
          <Route path="/final-package" element={<FinalPackage sessionId={mode === "live" ? sessionId : null} snapshot={snapshot} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppShell />
    </QueryClientProvider>
  );
}
