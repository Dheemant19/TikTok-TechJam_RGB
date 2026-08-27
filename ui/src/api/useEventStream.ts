import { useEffect, useRef, useState } from "react";
import { api } from "./client";
import type { RunEvent } from "./types";

export type ConnectionState = "connecting" | "connected" | "reconnecting" | "closed";

interface EventStreamResult {
  events: RunEvent[];
  connection: ConnectionState;
}

/**
 * Native EventSource auto-reconnects and resends the last `id:` it saw via
 * the `Last-Event-ID` header — this matches the server's
 * `cursor = max(after_sequence, Last-Event-ID)` replay contract exactly
 * (Plan_UI.md #7.2), so no manual reconnect/backlog logic is needed.
 */
export function useEventStream(sessionId: string | null, enabled: boolean): EventStreamResult {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const lastSequenceRef = useRef(0);

  useEffect(() => {
    if (!sessionId || !enabled) {
      setEvents([]);
      setConnection("closed");
      return;
    }
    setEvents([]);
    lastSequenceRef.current = 0;
    setConnection("connecting");
    const source = new EventSource(api.eventsUrl(sessionId, 0));
    let hasConnectedOnce = false;

    source.addEventListener("open", () => {
      hasConnectedOnce = true;
      setConnection("connected");
    });
    source.addEventListener("error", () => {
      setConnection(hasConnectedOnce ? "reconnecting" : "connecting");
    });
    source.addEventListener("run_event", (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as RunEvent;
      if (event.sequence <= lastSequenceRef.current) return; // duplicate delivery on reconnect
      lastSequenceRef.current = event.sequence;
      setEvents((previous) => [...previous, event]);
    });

    return () => {
      source.close();
      setConnection("closed");
    };
  }, [sessionId, enabled]);

  return { events, connection };
}
