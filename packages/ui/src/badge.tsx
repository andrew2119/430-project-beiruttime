import * as React from "react";
import { cn } from "./utils";
import { statusInk } from "./status-ink";

/**
 * Status badges built the T-token way: fg anchor + 8% bg + 20% border
 * derived via interoperable color-mix, with readable label ink.
 */
const HUES = {
  green: "var(--color-status-green)",
  orange: "var(--color-status-orange)",
  blue: "var(--color-status-blue)",
  pink: "var(--color-status-pink)",
  neutral: "var(--muted-foreground)",
} as const satisfies Record<string, string>;

function StatusBadge({
  hue = "neutral",
  className,
  children,
}: {
  hue?: keyof typeof HUES;
  className?: string;
  children: React.ReactNode;
}) {
  const c = HUES[hue];
  return (
    <span
      className={cn(
        "ui-badge",
        className
      )}
      style={{
        color: `color-mix(in oklab, ${statusInk(c)} 60%, var(--foreground))`,
        background: `color-mix(in oklab, ${c} 9%, transparent)`,
        boxShadow: `inset 0 0 0 1px color-mix(in oklab, ${c} 22%, transparent)`,
      }}
    >
      <span
        aria-hidden
        className="size-1.5 rounded-full"
        style={{ background: c }}
      />
      {children}
    </span>
  );
}

export { StatusBadge };
