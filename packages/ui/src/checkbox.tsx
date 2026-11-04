"use client";

import * as React from "react";
import { Check } from "lucide-react";
import { cn } from "./utils";

/**
 * Checkbox - a labelled native checkbox drawn with the shared recipe
 * (styles/ui.css `.ui-check*`): the real input stays the accessible control
 * and covers the drawn box, so `getByLabel`, keyboard toggling and the phone
 * hit-area rule all work natively while the fill and check glyph move on the
 * fast step instead of snapping.
 */
function Checkbox({
  className,
  children,
  ...props
}: Omit<React.ComponentProps<"input">, "type" | "children"> & {
  /** The visible label; it also names the input for assistive technology. */
  children: React.ReactNode;
}) {
  return (
    <label className={cn("ui-check", className)}>
      <span className="ui-check-box">
        <input type="checkbox" className="ui-check-input" {...props} />
        <Check className="ui-check-glyph size-3.5" strokeWidth={3} aria-hidden />
      </span>
      <span className="ui-check-label">{children}</span>
    </label>
  );
}

export { Checkbox };
