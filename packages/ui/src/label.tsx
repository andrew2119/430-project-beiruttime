"use client";

import * as React from "react";
import { cn } from "./utils";

function Label({ className, htmlFor, ...props }: React.ComponentProps<"label">) {
  // Every consumer names its control: `htmlFor` points at a real input id, or the
  // control is nested as children. Forwarded explicitly so the wrapper carries the
  // association contract instead of hiding it in a spread.
  return (
    <label
      htmlFor={htmlFor}
      className={cn(
        "ui-label",
        className,
      )}
      {...props}
    />
  );
}

export { Label };
