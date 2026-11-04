"use client";

import * as React from "react";
import {
  type Theme,
  nextTheme,
  themeCookieString,
} from "@/lib/theme";

/**
 * Client half of the theme system (doc 05 §1.2). The server layout stamps the
 * SSR value; this provider owns the runtime cycle. Theme switching is pure
 * CSS (tokens react to [data-theme]) — no force-rerender bridge like the
 * monolith's useTheme() (doc 05 §1.6 kills that pattern deliberately).
 */

type ThemeContextValue = {
  theme: Theme;
  cycleTheme: () => void;
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
    const next = nextTheme(theme);
    // Soft cross-fade between token sets (globals.css paces the snapshots).
    // The attribute is stamped inside the transition callback so the API
    // captures old → new; the effect above re-stamps the same value (no-op).
    const doc = document as Document & {
      startViewTransition?: (update: () => void) => unknown;
    };
    if (
      typeof doc.startViewTransition === "function" &&
      !window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      doc.startViewTransition(() => {
        document.documentElement.dataset.theme = next;
        setTheme(next);
      });
    } else {
      setTheme(next);
    }
  }, [theme]);

  const value = React.useMemo(
    () => ({ theme, cycleTheme }),
    [theme, cycleTheme],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}
