"use client";

import "./globals.css";
import { useEffect } from "react";

/**
 * Last-resort boundary for an error in the ROOT layout itself. It replaces
 * the document, so it carries its own minimal markup and inline styles (the
 * global stylesheet may not be there). Everything below the root layout is
 * caught by app/(app)/error.tsx and the department boundaries instead.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          fontFamily: "ui-sans-serif, system-ui, sans-serif",
          background: "var(--background)",
          color: "var(--foreground)",
        }}
      >
        <main style={{ textAlign: "center", padding: "2rem", maxWidth: "26rem" }}>
          <h1 style={{ fontSize: "1.125rem", margin: "0 0 0.5rem" }}>
            Beirut Time hit a problem
          </h1>
          <p style={{ fontSize: "0.875rem", opacity: 0.75, margin: "0 0 1.25rem" }}>
            The app could not start this page. Reloading usually clears it. لم يتم تحميل الصفحة.
            {error.digest ? ` Reference: ${error.digest}` : ""}
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              font: "inherit",
              fontWeight: "var(--ds-weight-strong)",
              padding: "0.5rem 1rem",
              borderRadius: "var(--ds-radius-chonk)",
              border: 0,
              background: "var(--primary)",
              color: "var(--primary-foreground)",
              cursor: "pointer",
            }}
          >
            Reload · حاول مجدداً
          </button>
        </main>
      </body>
    </html>
  );
}
