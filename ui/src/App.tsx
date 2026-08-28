import { Routes, Route } from "react-router-dom";
import { TopToolbar } from "./components/TopToolbar";
import { LiveWorkflow } from "./routes/LiveWorkflow";
import { DataProfile } from "./routes/DataProfile";
import { Experiments } from "./routes/Experiments";
import { ResearchLibrary } from "./routes/ResearchLibrary";
import { Resources } from "./routes/Resources";
import { FinalPackage } from "./routes/FinalPackage";
import { AutonomyLog } from "./routes/AutonomyLog";

export function App() {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <TopToolbar />
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <Routes>
          <Route path="/" element={<LiveWorkflow />} />
          <Route path="/data-profile" element={<DataProfile />} />
          <Route path="/experiments" element={<Experiments />} />
          <Route path="/research" element={<ResearchLibrary />} />
          <Route path="/resources" element={<Resources />} />
          <Route path="/package" element={<FinalPackage />} />
          <Route path="/autonomy" element={<AutonomyLog />} />
        </Routes>
      </div>
    </div>
  );
}
