import { useEffect, useRef } from "react";

/** Parse a `text/event-stream` body (fetch + ReadableStream). Calls onData for every `data:` message (raw string). */
export async function readSSE(res: Response, onData: (data: string) => void, signal?: AbortSignal): Promise<void> {
  if (!res.body) throw new Error("Response has no body");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  const flush = (block: string) => {
    const lines = block.split(/\r?\n/);
    const data: string[] = [];
    for (const line of lines) {
      if (!line || line.startsWith(":")) continue; // comment / heartbeat
      if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    if (data.length) onData(data.join("\n"));
  };
  const onAbort = () => void reader.cancel().catch(() => undefined);
  signal?.addEventListener("abort", onAbort);
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let m: RegExpExecArray | null;
      while ((m = /\r?\n\r?\n/.exec(buf))) {
        flush(buf.slice(0, m.index));
        buf = buf.slice(m.index + m[0].length);
      }
    }
    if (buf.trim()) flush(buf);
  } finally {
    signal?.removeEventListener("abort", onAbort);
  }
}

export function parseJSON<T>(raw: string): T | null {
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export interface SSEOptions<T> {
  /** Return true to close the stream (e.g. after run_finished). */
  onEvent: (ev: T) => boolean | void;
  enabled?: boolean;
  onOpen?: () => void;
  onError?: () => void;
}

/**
 * EventSource hook. The browser reconnects on its own; `onEvent` may return true to close for good.
 * The callback is kept in a ref, so it never causes a reconnect.
 */
export function useSSE<T>(url: string | null, opts: SSEOptions<T>): void {
  const cb = useRef(opts);
  cb.current = opts;
  const enabled = opts.enabled !== false && !!url;
  useEffect(() => {
    if (!enabled || !url) return;
    let es: EventSource | null = new EventSource(url);
    es.onopen = () => cb.current.onOpen?.();
    es.onerror = () => cb.current.onError?.();
    es.onmessage = (m) => {
      const ev = parseJSON<T>(m.data);
      if (!ev) return;
      if (cb.current.onEvent(ev) === true) {
        es?.close();
        es = null;
      }
    };
    return () => {
      es?.close();
      es = null;
    };
  }, [url, enabled]);
}
