"use client";

import * as React from "react";
import {
  type Theme,
  nextTheme,
  themeCookieString,
} from "@/lib/theme";
import { beginThemeIntent } from '@/lib/theme-intent';

/** The server stamps the initial preference. Existing controls keep their
 * transition path; new controls may commit an atomic, externally paced change. */

type ThemeContextValue = {
  theme: Theme;
  cycleTheme: () => void;
  applyTheme: (theme: Theme) => void;
};

const ThemeContext = React.createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const ctx = React.useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}

export function ThemeProvider({
  initialTheme,
  children,
}: {
  initialTheme: Theme;
  children: React.ReactNode;
}) {
  const [theme, setTheme] = React.useState<Theme>(initialTheme);

  // Re-stamp + persist on every change (and on mount, which harmlessly
  // refreshes the cookie's Max-Age). The cookie is what the server layout
  // reads next load — same single source the runtime uses.
  React.useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.cookie = themeCookieString(
      theme,
      window.location.protocol === "https:",
    );
  }, [theme]);

  const cycleTheme = React.useCallback(() => {
    let transition: {finished?: Promise<void>; skipTransition?: () => void} | undefined;
    const intent = beginThemeIntent(() => transition?.skipTransition?.());
    const next = nextTheme(theme);
    // Soft cross-fade between token sets (globals.css paces the snapshots).
    // The attribute is stamped inside the transition callback so the API
    // captures old → new; the effect above re-stamps the same value (no-op).
    const doc = document as Document & {
      startViewTransition?: (update: () => void) => {finished?: Promise<void>; skipTransition?: () => void};
    };
    if (
      typeof doc.startViewTransition === "function" &&
      !window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      transition = doc.startViewTransition(() => {
        if (!intent.isCurrent()) return;
        document.documentElement.dataset.theme = next;
        setTheme(next);
      });
      void transition.finished?.catch(() => {}).finally(() => intent.release());
    } else {
      setTheme(next);
      intent.release();
    }
  }, [theme]);

  const applyTheme = React.useCallback((next: Theme) => {
    document.documentElement.dataset.theme = next;
    setTheme(next);
  }, []);

  const value = React.useMemo(
    () => ({ theme, cycleTheme, applyTheme }),
    [theme, cycleTheme, applyTheme],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}
