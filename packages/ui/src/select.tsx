"use client";

import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "./utils";
import { useDirection } from "@radix-ui/react-direction";

export interface SelectOption {
  value: string;
  label: React.ReactNode;
  disabled?: boolean;
}

export interface SelectProps {
  value: string;
  onValueChange: (value: string) => void;
  options: readonly SelectOption[];
  /** Accessible name for the trigger; use `aria-labelledby` instead when a visible label names it. */
  "aria-label"?: string;
  "aria-labelledby"?: string;
  id?: string;
  placeholder?: string;
  size?: "md" | "sm";
  disabled?: boolean;
  /** Show a filter field above the options; defaults to on for more than eight options. */
  searchable?: boolean;
  align?: "start" | "end";
  className?: string;
  menuClassName?: string;
  onOpenChange?: (open: boolean) => void;
}

const loadMenu = () => import("./select-menu");
const SelectMenu = React.lazy(loadMenu);

const OPEN_KEYS = new Set(["Enter", " ", "ArrowDown", "ArrowUp"]);

/**
 * The single-choice dropdown (v0 / shadcn Select role). Every department's dropdown
 * shares one look, one motion contract and one keyboard model through this primitive;
 * the menu-backed implementation lives in select-menu.tsx and loads on the first
 * engagement (pointer, keyboard or focus), so a route that only shows closed dropdowns
 * does not pay for the menu primitives in its first-load JavaScript. Until then this
 * renders the same `.ui-select` trigger (same classes, name, value and ARIA), so focus
 * rings, hit targets and screenshots are identical; the chunk is warmed on hover and
 * focus so the first open is not delayed.
 */
export function Select(props: SelectProps) {
  const [engaged, setEngaged] = React.useState<null | { open: boolean }>(null);
  if (engaged) {
    return (
      <React.Suspense fallback={<InertTrigger {...props} />}>
        <SelectMenu {...props} defaultOpen={engaged.open} autoFocusTrigger />
      </React.Suspense>
    );
  }
  return (
    <InertTrigger
      {...props}
      onEngage={(open) => {
        if (open) props.onOpenChange?.(true);
        setEngaged({ open });
      }}
    />
  );
}

function InertTrigger({
  value,
  options,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
  id,
  placeholder,
  size = "md",
  disabled = false,
  className,
  onEngage,
}: SelectProps & { onEngage?: (open: boolean) => void }) {
  const direction = useDirection();
  const selected = options.find((option) => option.value === value);
  const warm = () => void loadMenu();
  return (
    <button
      type="button"
      id={id}
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledBy}
      aria-haspopup="menu"
      aria-expanded={false}
      data-state="closed"
      data-value={value}
      disabled={disabled}
      className={cn("ui-select", size === "sm" && "ui-select-sm", className)}
      onPointerEnter={warm}
      onFocus={warm}
      onPointerDown={(event) => {
        // Same gesture Radix's trigger reacts to: the primary button opens the menu.
        if (event.button !== 0 || event.ctrlKey) return;
        event.preventDefault();
        onEngage?.(true);
      }}
      onClick={() => onEngage?.(true)}
      onKeyDown={(event) => {
        if (!OPEN_KEYS.has(event.key)) return;
        event.preventDefault();
        onEngage?.(true);
      }}
    >
      <span className={cn("ui-select-value", !selected && "text-muted-foreground")}>
        {selected ? selected.label : placeholder ?? (direction === "rtl" ? "اختر…" : "Select…")}
      </span>
      <ChevronDown className="ui-select-caret" aria-hidden />
    </button>
  );
}
