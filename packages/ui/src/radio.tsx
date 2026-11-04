"use client";

import * as React from "react";
import { Check } from "lucide-react";
import { cn } from "./utils";

/**
 * Radio - a labelled native radio, one of a named group, drawn with the same shared
 * recipe as `Checkbox` (styles/ui.css `.ui-check*`): a pick-one list of check rows, as
 * the one-campaign picker's (components/proto/add-creator/one-campaign-picker.tsx). The
 * real input stays the accessible control and covers the drawn box, so the browser's
 * own radio group keyboard (arrows move the choice) works natively.
 */
function Radio({
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
        <input type="radio" className="ui-check-input" {...props} />
        <Check className="ui-check-glyph size-3.5" strokeWidth={3} aria-hidden />
      </span>
      <span className="ui-check-label">{children}</span>
    </label>
  );
}

export { Radio };
