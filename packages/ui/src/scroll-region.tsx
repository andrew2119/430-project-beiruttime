"use client";

/* eslint jsx-a11y/no-noninteractive-tabindex: "error", jsx-a11y/no-noninteractive-element-interactions: "error" */
/* eslint-disable jsx-a11y/no-noninteractive-tabindex -- WCAG keyboard access to this named overflow viewport requires a tab stop. */

import type { ReactNode } from "react";
import { cn } from "./utils";

/** A named, keyboard-reachable viewport for charts and wide department tables. */
export function ScrollRegion({ label, className, children }: { label: string; className?: string; children: ReactNode }) {
  return (
    // WCAG 2.1.1 requires keyboard access to overflow content. A region is not a button.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      className={cn("overflow-x-auto focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2", className)}
      onKeyDown={(event) => {
        // Mobile WebKit does not natively scroll a focused region with arrow keys.
        if (event.target !== event.currentTarget || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        event.currentTarget.scrollBy({ left: event.key === "ArrowRight" ? 80 : -80 });
      }}
    >
      {children}
    </div>
  );
}
