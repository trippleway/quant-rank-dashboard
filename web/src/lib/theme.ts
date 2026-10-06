import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";

const KEY = "qrd-theme";

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(currentTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.dispatchEvent(new CustomEvent("qrd-theme", { detail: theme }));
  }, [theme]);
  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(KEY, next);
      } catch {
        /* storage unavailable: theme still applies for this session */
      }
      return next;
    });
  }, []);
  return [theme, toggle];
}

/** Subscribe to theme changes (charts rebuild their options with new tokens). */
export function useThemeVersion(): Theme {
  const [t, setT] = useState<Theme>(currentTheme);
  useEffect(() => {
    const on = () => setT(currentTheme());
    window.addEventListener("qrd-theme", on);
    return () => window.removeEventListener("qrd-theme", on);
  }, []);
  return t;
}

export interface Tokens {
  ink1: string;
  ink2: string;
  muted: string;
  grid: string;
  axis: string;
  surface: string;
  surface2: string;
  up: string;
  down: string;
  series: string[];
  divNeg: string;
  divMid: string;
  divPos: string;
  good: string;
  warning: string;
  critical: string;
  mono: string;
}

export function readTokens(): Tokens {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return {
    ink1: v("--ink-1"),
    ink2: v("--ink-2"),
    muted: v("--ink-muted"),
    grid: v("--grid"),
    axis: v("--axis"),
    surface: v("--surface-1"),
    surface2: v("--surface-2"),
    up: v("--up"),
    down: v("--down"),
    series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--series-${i}`)),
    divNeg: v("--div-neg"),
    divMid: v("--div-mid"),
    divPos: v("--div-pos"),
    good: v("--status-good"),
    warning: v("--status-warning"),
    critical: v("--status-critical"),
    mono: v("--mono"),
  };
}
