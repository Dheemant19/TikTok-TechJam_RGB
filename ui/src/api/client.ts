import type { AllowedAction, ArtifactResponse, ChatTurnDTO, JsonRecord, RunEventDTO, SessionChatResponse, SessionListItem, SessionSnapshotDTO } from "./types";

async function asJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    let detail: string | undefined;
    if (body && typeof body === "object" && "detail" in body) {
      const candidate = body.detail;
      detail = typeof candidate === "string" ? candidate : undefined;
    }
    throw new Error(detail ?? `${response.status} ${response.statusText}`);
  }
  // The observer API is this frontend's only server; its FastAPI response
  // models (flowstate/contract/models.py) are the schema of record.
  return (await response.json()) as T;
}

async function asEmpty(response: Response): Promise<void> {
  if (!response.ok) await asJson<unknown>(response);
}

function postJson<T>(url: string, body: unknown): Promise<T> {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((response) => asJson<T>(response));
}

export const api = {
  listSessions: (): Promise<SessionListItem[]> => fetch("/api/v1/sessions").then((response) => asJson(response)),

  startSession: (challengeConfigPath: string, budgetConfigPath: string): Promise<{ session_id: string; snapshot_url: string }> =>
    postJson("/api/v1/sessions", { challenge_config_path: challengeConfigPath, budget_config_path: budgetConfigPath }),

  deleteSession: (sessionId: string): Promise<void> =>
    fetch(`/api/v1/sessions/${sessionId}`, { method: "DELETE" }).then(asEmpty),

  packageFileUrl: (
    sessionId: string,
    filename: "predictions.csv" | "manifest.json",
  ): string =>
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/package/${filename}`,

  getSnapshot: (sessionId: string): Promise<SessionSnapshotDTO> =>
    fetch(`/api/v1/sessions/${sessionId}/snapshot`).then((response) => asJson(response)),

  getReplay: (sessionId: string): Promise<{ mode: string; events: RunEventDTO[]; final_snapshot: SessionSnapshotDTO }> =>
    fetch(`/api/v1/sessions/${sessionId}/replay`).then((response) => asJson(response)),

  getExecution: (sessionId: string, componentId: string, executionId: string): Promise<{ component_id: string; execution_id: string; attempts: RunEventDTO[] }> =>
    fetch(`/api/v1/sessions/${sessionId}/components/${componentId}/executions/${executionId}`).then((response) => asJson(response)),

  getArtifact: (artifactId: string): Promise<ArtifactResponse> =>
    fetch(`/api/v1/artifacts/${artifactId}`).then((response) => asJson(response)),

  control: (sessionId: string, action: Extract<AllowedAction, "pause" | "resume" | "cancel">, expectedSequence: number): Promise<{ accepted: boolean; action: string }> =>
    postJson(`/api/v1/sessions/${sessionId}/${action}`, { expected_sequence: expectedSequence }),

  packageSession: (sessionId: string): Promise<JsonRecord> =>
    postJson(`/api/v1/sessions/${sessionId}/package`, { confirmation: sessionId }),

  chatSession: (
    sessionId: string,
    question: string,
    history: ChatTurnDTO[],
  ): Promise<SessionChatResponse> =>
    postJson(`/api/v1/sessions/${encodeURIComponent(sessionId)}/chat`, {
      question,
      history,
    }),
};

/**
 * Opens the session's Server-Sent Events stream from `afterSequence` (0
 * replays full history first, per api/server.py) and keeps tailing live
 * updates. Returns a teardown function. The browser's native `EventSource`
 * automatically resends `Last-Event-ID` on reconnect, matching the backend's
 * sequence-gap handling (Plan_UI.md #1.5, #7.2).
 */
export function subscribeToEvents(
  sessionId: string,
  afterSequence: number,
  onEvent: (event: RunEventDTO) => void,
  onConnectionChange: (state: "open" | "retrying" | "closed") => void,
): () => void {
  const source = new EventSource(`/api/v1/sessions/${sessionId}/events?after_sequence=${afterSequence}`);
  source.addEventListener("open", () => onConnectionChange("open"));
  source.addEventListener("run_event", (message) => {
    // The server only ever puts RunEvent JSON (flowstate.contract.models.RunEvent) on this channel.
    const messageEvent = message as MessageEvent<string>;
    onEvent(JSON.parse(messageEvent.data) as RunEventDTO);
  });
  source.addEventListener("error", () => {
    onConnectionChange(source.readyState === EventSource.CLOSED ? "closed" : "retrying");
  });
  return () => source.close();
}
