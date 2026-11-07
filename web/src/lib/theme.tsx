import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { lsGet, lsSet } from "./storage";

type Resolved = "light" | "dark";
interface ThemeCtx { theme: Resolved; toggle: () => void }
const Ctx = createContext<ThemeCtx>({ theme: "light", toggle: () => undefined });

const systemTheme = (): Resolved =>
  typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [explicit, setExplicit] = useState<Resolved | null>(() => {
    const v = lsGet("atom-theme");
    return v === "dark" || v === "light" ? v : null;
  });
  const [system, setSystem] = useState<Resolved>(systemTheme);
  useEffect(() => {
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const on = () => setSystem(mq.matches ? "dark" : "light");
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  const theme = explicit ?? system;
  useEffect(() => {
    if (explicit) document.documentElement.dataset.theme = explicit;
    else delete document.documentElement.dataset.theme;
  }, [explicit]);
  const toggle = useCallback(() => {
    const next: Resolved = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next; // apply before re-render so charts read fresh colours
    setExplicit(next);
    lsSet("atom-theme", next);
  }, [theme]);
  const value = useMemo(() => ({ theme, toggle }), [theme, toggle]);
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
