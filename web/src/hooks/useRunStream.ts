import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api } from "../api/client";
import { useSSE } from "../api/sse";
import type { RunEvent } from "../api/types";
import { initialLive, liveReducer } from "../lib/runState";

export type ConnState = "idle" | "connecting" | "live" | "reconnecting" | "closed";

/**
 * Subscribes to /api/runs/{id}/events while `enabled`. The stream replays history on every (re)connect,
 * so events are de-duplicated by `seq` before reaching the reducer.
 */
export function useRunStream(runId: string, enabled: boolean, onFinished?: () => void) {
  const [state, dispatch] = useReducer(liveReducer, initialLive);
  const [conn, setConn] = useState<ConnState>("idle");
  const seen = useRef<Set<number>>(new Set());
  const [dupes, setDupes] = useState(0);
  const onFin = useRef(onFinished);
  onFin.current = onFinished;

  useEffect(() => {
    seen.current = new Set();
    dispatch({ type: "__reset" });
    setConn(enabled ? "connecting" : "idle");
    setDupes(0);
  }, [runId, enabled]);

  const onEvent = useCallback((ev: RunEvent): boolean => {
    if (typeof ev.seq === "number") {
      if (seen.current.has(ev.seq)) {
        setDupes((d) => d + 1);
        return false;
      }
      seen.current.add(ev.seq);
    }
    dispatch(ev);
    if (ev.type === "run_finished") {
      setConn("closed");
      onFin.current?.();
      return true; // close the EventSource: server ends the stream after run_finished
    }
    return false;
  }, []);

  useSSE<RunEvent>(enabled ? api.runEventsUrl(runId) : null, {
    enabled,
    onEvent,
    onOpen: () => setConn("live"),
    onError: () => setConn((c) => (c === "closed" ? c : "reconnecting")),
  });

  return { state, conn, dupes };
}
