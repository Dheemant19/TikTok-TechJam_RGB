import { useEffect } from "react";
import { Routes, Route } from "react-router-dom";
import { TopToolbar } from "./components/TopToolbar";
import { RouteEdgeNavigation } from "./components/RouteEdgeNavigation";
import { LiveWorkflow } from "./routes/LiveWorkflow";
import { DataProfile } from "./routes/DataProfile";
import { Experiments } from "./routes/Experiments";
import { ResearchLibrary } from "./routes/ResearchLibrary";
import { Resources } from "./routes/Resources";
import { FinalPackage } from "./routes/FinalPackage";
import { AutonomyLog } from "./routes/AutonomyLog";
import { useRunStore } from "./liveworkflow/runStore";

export function App() {
  useEffect(() => {
    void useRunStore.getState().bootstrap();
  }, []);

  return (
    <div className="app-shell">
      <TopToolbar pillFluidity={0.7} />
      <main className="app-shell__content">
        <Routes>
          <Route path="/" element={<LiveWorkflow />} />
          <Route path="/data-profile" element={<DataProfile />} />
          <Route path="/experiments" element={<Experiments />} />
          <Route path="/research" element={<ResearchLibrary />} />
          <Route path="/resources" element={<Resources />} />
          <Route path="/package" element={<FinalPackage />} />
          <Route path="/autonomy" element={<AutonomyLog />} />
        </Routes>
      </main>
      <RouteEdgeNavigation />
    </div>
  );
}
