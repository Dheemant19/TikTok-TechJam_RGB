import {
  ApiError,
  type ArtifactRef,
  type ComponentExecution,
  type ControlResponse,
  type FinalizationManifest,
  type ReplayResponse,
  type SessionListItem,
  type SessionSnapshot,
  type StartSessionRequest,
  type StartSessionResponse,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE_PATH ?? "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, body.detail ?? response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  listSessions: () => request<SessionListItem[]>("/sessions"),

  startSession: (body: StartSessionRequest) =>
    request<StartSessionResponse>("/sessions", { method: "POST", body: JSON.stringify(body) }),

  getSnapshot: (sessionId: string) => request<SessionSnapshot>(`/sessions/${sessionId}/snapshot`),

  getComponentExecution: (sessionId: string, componentId: string, executionId: string) =>
    request<ComponentExecution>(`/sessions/${sessionId}/components/${componentId}/executions/${executionId}`),

  getArtifact: (artifactId: string) => request<ArtifactRef>(`/artifacts/${artifactId}`),

  pause: (sessionId: string, expectedSequence: number) =>
    request<ControlResponse>(`/sessions/${sessionId}/pause`, {
      method: "POST",
      body: JSON.stringify({ expected_sequence: expectedSequence }),
    }),

  resume: (sessionId: string, expectedSequence: number) =>
    request<ControlResponse>(`/sessions/${sessionId}/resume`, {
      method: "POST",
      body: JSON.stringify({ expected_sequence: expectedSequence }),
    }),

  cancel: (sessionId: string, expectedSequence: number) =>
    request<ControlResponse>(`/sessions/${sessionId}/cancel`, {
      method: "POST",
      body: JSON.stringify({ expected_sequence: expectedSequence }),
    }),

  packageSubmission: (sessionId: string, confirmation: string) =>
    request<FinalizationManifest>(`/sessions/${sessionId}/package`, {
      method: "POST",
      body: JSON.stringify({ confirmation }),
    }),

  getReplay: (sessionId: string) => request<ReplayResponse>(`/sessions/${sessionId}/replay`),

  eventsUrl: (sessionId: string, afterSequence = 0) =>
    `${BASE}/sessions/${sessionId}/events?after_sequence=${afterSequence}`,
};
