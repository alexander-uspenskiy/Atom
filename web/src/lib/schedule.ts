import type { ScheduleTrigger } from "../api/types";

export const CRON_PRESETS: { label: string; expr: string }[] = [
  { label: "Every weekday 08:00", expr: "0 8 * * 1-5" },
  { label: "Every day 09:00", expr: "0 9 * * *" },
  { label: "Every hour", expr: "0 * * * *" },
  { label: "Every 15 minutes", expr: "*/15 * * * *" },
  { label: "Every Monday 09:00", expr: "0 9 * * 1" },
  { label: "1st of month 08:00", expr: "0 8 1 * *" },
];

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const pad = (n: number | string) => String(n).padStart(2, "0");

export function describeCron(expr: string): string {
  const p = expr.trim().split(/\s+/);
  if (p.length !== 5) return `cron ${expr}`;
  const [m, h, dom, mon, dow] = p;
  const num = (s: string) => /^\d+$/.test(s);
  const r = /^\*\/(\d+)$/.exec(m);
  if (r && h === "*" && dom === "*" && mon === "*" && dow === "*") return `Every ${r[1]} minutes`;
  if (m === "0" && h === "*" && dom === "*" && mon === "*" && dow === "*") return "Every hour";
  if (num(m) && num(h) && dom === "*" && mon === "*") {
    const t = `${pad(h)}:${pad(m)}`;
    if (dow === "*") return `Every day at ${t}`;
    if (dow === "1-5") return `Weekdays at ${t}`;
    if (num(dow)) return `Every ${DOW[Number(dow)] ?? dow} at ${t}`;
  }
  if (num(m) && num(h) && num(dom) && mon === "*" && dow === "*") return `Day ${dom} of every month at ${pad(h)}:${pad(m)}`;
  return `cron ${expr}`;
}

export function describeInterval(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "Every ?";
  if (seconds % 86400 === 0) return `Every ${seconds / 86400 === 1 ? "day" : `${seconds / 86400} days`}`;
  if (seconds % 3600 === 0) return `Every ${seconds / 3600 === 1 ? "hour" : `${seconds / 3600} hours`}`;
  if (seconds % 60 === 0) return `Every ${seconds / 60 === 1 ? "minute" : `${seconds / 60} minutes`}`;
  return `Every ${seconds}s`;
}

export function describeTrigger(t?: ScheduleTrigger | null): string {
  if (!t) return "—";
  if (t.type === "cron") return describeCron(t.expr);
  if (t.type === "interval") return describeInterval(t.seconds);
  if (t.type === "once") return `Once at ${t.at.replace("T", " ").slice(0, 16)}`;
  return "—";
}

export function timezones(): string[] {
  try {
    const f = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf;
    const list = f ? f("timeZone") : [];
    if (list.length) return list.includes("UTC") ? list : ["UTC", ...list];
  } catch {
    /* fall through */
  }
  return ["UTC", "America/New_York", "America/Chicago", "America/Los_Angeles", "America/Sao_Paulo", "Europe/London", "Europe/Berlin", "Asia/Tokyo", "Asia/Kolkata", "Australia/Sydney"];
}

export const localTimezone = (): string => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
};
