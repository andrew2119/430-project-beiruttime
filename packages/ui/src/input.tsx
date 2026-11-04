"use client";

import * as React from "react";
import { cn } from "./utils";

function Input({ className, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      className={cn(
        "ui-input",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
