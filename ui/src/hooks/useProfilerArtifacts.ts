import { useMemo } from "react";
import type { RunEvent } from "@/api/types";

interface ProfilerArtifactIds {
  profileArtifactId: string | null;
  visualizationArtifactId: string | null;
  transformReceiptArtifactId: string | null;
  transformStateArtifactId: string | null;
}

/** The data_profiler "completed" event embeds artifact refs in its payload. */
export function useProfilerArtifacts(events: RunEvent[]): ProfilerArtifactIds {
  return useMemo(() => {
    const event = [...events].reverse().find((item) => item.component_id === "data_profiler" && item.event_type === "completed");
    const payload = event?.payload as
      | { profile?: { profile?: { artifact_id?: string }; visualization?: { artifact_id?: string } }; transform?: { receipt?: { artifact_id?: string }; state?: { artifact_id?: string } } }
      | undefined;
    return {
      profileArtifactId: payload?.profile?.profile?.artifact_id ?? null,
      visualizationArtifactId: payload?.profile?.visualization?.artifact_id ?? null,
      transformReceiptArtifactId: payload?.transform?.receipt?.artifact_id ?? null,
      transformStateArtifactId: payload?.transform?.state?.artifact_id ?? null,
    };
  }, [events]);
}
