import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { lsGet, lsSet } from "./storage";

type Resolved = "light" | "dark";
export type ThemeMode = "auto" | "light" | "dark";
interface ThemeCtx { theme: Resolved; mode: ThemeMode; toggle: () => void }
const Ctx = createContext<ThemeCtx>({ theme: "light", mode: "auto", toggle: () => undefined });

const NEXT: Record<ThemeMode, ThemeMode> = { auto: "light", light: "dark", dark: "auto" };

const systemTheme = (): Resolved =>
  typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(() => {
    const v = lsGet("atom-theme");
    return v === "dark" || v === "light" ? v : "auto";
  });
  const [system, setSystem] = useState<Resolved>(systemTheme);
  useEffect(() => {
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const on = () => setSystem(mq.matches ? "dark" : "light");
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  const theme: Resolved = mode === "auto" ? system : mode;
  useEffect(() => {
    if (mode === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = mode;
  }, [mode]);
  const toggle = useCallback(() => {
    const next = NEXT[mode];
    // apply before re-render so charts read fresh colours
    if (next === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = next;
    setMode(next);
    lsSet("atom-theme", next);
  }, [mode]);
  const value = useMemo(() => ({ theme, mode, toggle }), [theme, mode, toggle]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);

/** Concrete colour strings (read from CSS variables) for charts; recomputed on theme change. */
export function useChartColors() {
  const { theme } = useTheme();
  return useMemo(() => {
    void theme;
    const cs = getComputedStyle(document.documentElement);
    const v = (n: string) => `rgb(${cs.getPropertyValue(`--${n}`).trim().split(/\s+/).join(",")})`;
    return {
      accent: v("accent"), info: v("info"), ok: v("ok"), warn: v("warn"), err: v("err"),
      muted: v("muted"), line: v("line"), fg: v("fg"), surface: v("surface"),
    };
  }, [theme]);
}
