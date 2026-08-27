import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { StartSessionRequest } from "./types";

export function useSessionList() {
  return useQuery({ queryKey: ["sessions"], queryFn: api.listSessions, refetchInterval: 15_000 });
}

export function useSnapshot(sessionId: string | null) {
  return useQuery({
    queryKey: ["snapshot", sessionId],
    queryFn: () => api.getSnapshot(sessionId as string),
    enabled: Boolean(sessionId),
  });
}

export function useComponentExecution(sessionId: string | null, componentId: string | null, executionId: string | null) {
  return useQuery({
    queryKey: ["execution", sessionId, componentId, executionId],
    queryFn: () => api.getComponentExecution(sessionId as string, componentId as string, executionId as string),
    enabled: Boolean(sessionId && componentId && executionId),
  });
}

export function useArtifact(artifactId: string | null) {
  return useQuery({
    queryKey: ["artifact", artifactId],
    queryFn: () => api.getArtifact(artifactId as string),
    enabled: Boolean(artifactId),
  });
}

export function useReplay(sessionId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["replay", sessionId],
    queryFn: () => api.getReplay(sessionId as string),
    enabled: Boolean(sessionId) && enabled,
  });
}

export function useStartSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: StartSessionRequest) => api.startSession(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sessions"] }),
  });
}

export function useSessionControl(sessionId: string) {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["snapshot", sessionId] });
  return {
    pause: useMutation({ mutationFn: (seq: number) => api.pause(sessionId, seq), onSuccess: invalidate }),
    resume: useMutation({ mutationFn: (seq: number) => api.resume(sessionId, seq), onSuccess: invalidate }),
    cancel: useMutation({ mutationFn: (seq: number) => api.cancel(sessionId, seq), onSuccess: invalidate }),
    packageSubmission: useMutation({
      mutationFn: (confirmation: string) => api.packageSubmission(sessionId, confirmation),
      onSuccess: invalidate,
    }),
  };
}
