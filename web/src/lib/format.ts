const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

export function fmtTokens(n?: number | null): string {
  if (!isNum(n)) return "–";
  const a = Math.abs(n);
  if (a >= 1e6) return `${(n / 1e6).toFixed(a >= 1e7 ? 0 : 1)}M`;
  if (a >= 1e4) return `${(n / 1e3).toFixed(0)}k`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return String(Math.round(n));
}

export function fmtInt(n?: number | null): string {
  return isNum(n) ? Math.round(n).toLocaleString() : "–";
}

/** 0.4s, 9.2s, 36s, 1m 12s, 2h 5m */
export function fmtDuration(s?: number | null): string {
  if (!isNum(s) || s < 0) return "–";
  if (s < 10) return `${s.toFixed(1)}s`;
  if (s < 60) return `${Math.round(s)}s`;
  const total = Math.round(s);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m ${sec}s`;
}

export function fmtMs(ms?: number | null): string {
  if (!isNum(ms)) return "–";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

export function fmtTps(n?: number | null): string {
  return isNum(n) ? `${n >= 100 ? Math.round(n) : n.toFixed(1)} tok/s` : "–";
}

export function fmtPct(r?: number | null, digits = 0): string {
  return isNum(r) ? `${(r * 100).toFixed(digits)}%` : "–";
}

export function cachedPct(cached?: number | null, prompt?: number | null): number | null {
  return isNum(cached) && isNum(prompt) && prompt > 0 ? cached / prompt : null;
}

export function fmtDateTime(ts?: number | null): string {
  if (!isNum(ts) || ts <= 0) return "–";
  return new Date(ts * 1000).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function fmtClock(ts?: number | null): string {
  if (!isNum(ts) || ts <= 0) return "–";
  return new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** "in 5m" / "3m ago" / "just now" */
export function fmtRelative(ts?: number | null, now: number = Date.now() / 1000): string {
  if (!isNum(ts) || ts <= 0) return "–";
  const d = ts - now;
  const a = Math.abs(d);
  if (a < 5) return "just now";
  let v: string;
  if (a < 60) v = `${Math.round(a)}s`;
  else if (a < 3600) v = `${Math.round(a / 60)}m`;
  else if (a < 86400) {
    const totalMin = Math.round(a / 60);
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    v = m && h < 6 ? `${h}h ${m}m` : `${Math.round(a / 3600)}h`;
  } else v = `${Math.round(a / 86400)}d`;
  return d > 0 ? `in ${v}` : `${v} ago`;
}

export function truncate(s: string | null | undefined, n: number): string {
  if (!s) return "";
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

export function prettyJSON(v: unknown): string {
  if (v === undefined) return "";
  if (typeof v === "string") {
    try {
      return JSON.stringify(JSON.parse(v), null, 2);
    } catch {
      return v;
    }
  }
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

/** Compact one-line preview of tool arguments. */
export function argsPreview(args: unknown, max = 120): string {
  if (args === null || args === undefined) return "";
  if (typeof args === "string") return truncate(args, max);
  try {
    const s = JSON.stringify(args);
    return truncate(s === "{}" ? "" : s, max);
  } catch {
    return "";
  }
}

export function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function slugOk(name: string): boolean {
  return /^[a-z0-9]+(-[a-z0-9]+)*$/.test(name);
}

export function hostOf(url?: string | null): string {
  if (!url) return "";
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/** "Nov 10, 2026, 15:42:07" – full date and time with seconds, for message timestamps. */
export function fmtFull(ts?: number | null): string {
  if (!isNum(ts) || ts <= 0) return "";
  return new Date(ts * 1000).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}
