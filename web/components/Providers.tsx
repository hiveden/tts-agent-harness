"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ThemedToaster } from "./ThemedToaster";

// ---------------------------------------------------------------------------
// Theme context (replaces next-themes for Next.js 16 compatibility)
// ---------------------------------------------------------------------------

type Theme = "light" | "dark" | "system";
type ResolvedTheme = "light" | "dark";

interface ThemeCtx {
  theme: Theme;
  resolvedTheme: ResolvedTheme;
  setTheme: (t: Theme) => void;
}

const ThemeContext = createContext<ThemeCtx>({
  theme: "system",
  resolvedTheme: "light",
  setTheme: () => {},
});

export const useTheme = () => useContext(ThemeContext);

const STORAGE_KEY = "theme";

function getSystemTheme(): ResolvedTheme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function resolve(theme: Theme): ResolvedTheme {
  return theme === "system" ? getSystemTheme() : theme;
}

function applyClass(resolved: ResolvedTheme) {
  const el = document.documentElement;
  el.classList.toggle("dark", resolved === "dark");
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function Providers({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("system");
  const [resolved, setResolved] = useState<ResolvedTheme>("light");

  // Init from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY) as Theme | null;
    const t = stored === "light" || stored === "dark" ? stored : "system";
    setThemeState(t);
    const r = resolve(t);
    setResolved(r);
    applyClass(r);
  }, []);

  // Listen to system preference changes
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      if (theme === "system") {
        const r = getSystemTheme();
        setResolved(r);
        applyClass(r);
      }
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [theme]);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    localStorage.setItem(STORAGE_KEY, t);
    const r = resolve(t);
    setResolved(r);
    applyClass(r);
  }, []);

  const ctx = useMemo(() => ({ theme, resolvedTheme: resolved, setTheme }), [theme, resolved, setTheme]);

  return (
    <ThemeContext.Provider value={ctx}>
      {children}
      <ThemedToaster />
    </ThemeContext.Provider>
  );
}
