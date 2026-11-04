"use client";

import * as React from "react";
import { ChevronDown, Search } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "./dropdown-menu";
import { Input } from "./input";
import { cn } from "./utils";
import { useDirection } from "@radix-ui/react-direction";

import type { SelectOption, SelectProps } from "./select";

export interface SelectMenuProps extends SelectProps {
  /** Open the menu as soon as the lazily loaded implementation mounts. */
  defaultOpen?: boolean;
  /** Return keyboard focus to the trigger after the placeholder handed over. */
  autoFocusTrigger?: boolean;
}

/** Re-exported for the lazy boundary's type checks. */
export type { SelectOption, SelectProps };

/**
 * The menu-backed implementation of the shared Select: the `.ui-select` trigger on the
 * animated `.pg-popover ui-menu` surface (open on the popover step, close on the fast
 * step, transform-origin from the popper side, collapsed by the global reduced-motion
 * baseline), radio items with the shared highlight and checked indicator, roving keyboard
 * navigation, typeahead, Escape and focus return to the trigger. It is a lazy chunk:
 * components/ui/select.tsx renders an identical inert trigger first and loads this module
 * on the first engagement, so routes that only show closed dropdowns do not carry the
 * menu primitives in their first-load JavaScript (release verdict a33f690, performance).
 */
export default function SelectMenu({
  value,
  onValueChange,
  options,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
  id,
  placeholder,
  size = "md",
  disabled = false,
  searchable,
  align = "start",
  className,
  menuClassName,
  onOpenChange,
  defaultOpen = false,
  autoFocusTrigger = false,
}: SelectMenuProps) {
  const direction = useDirection();
  const [open, setOpen] = React.useState(defaultOpen);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  React.useEffect(() => {
    // The placeholder trigger that handed over had focus; keep it on the real trigger.
    // When the menu opens on mount, Radix moves focus into the menu from here.
    if (autoFocusTrigger) triggerRef.current?.focus({ preventScroll: true });
    // Mount-time only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [query, setQuery] = React.useState("");
  const showSearch = searchable ?? options.length > 8;
  const filtered = showSearch && query
    ? options.filter((option) => String(option.label).toLowerCase().includes(query.toLowerCase()))
    : options;
  const selected = options.find((option) => option.value === value);

  return (
    <DropdownMenu
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
        onOpenChange?.(next);
      }}
    >
      <DropdownMenuTrigger asChild disabled={disabled}>
        <button
          ref={triggerRef}
          type="button"
          id={id}
          aria-label={ariaLabel}
          aria-labelledby={ariaLabelledBy}
          data-value={value}
          className={cn("ui-select", size === "sm" && "ui-select-sm", className)}
        >
          <span className={cn("ui-select-value", !selected && "text-muted-foreground")}>
            {selected ? selected.label : placeholder ?? (direction === "rtl" ? "اختر…" : "Select…")}
          </span>
          <ChevronDown className="ui-select-caret" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align={align} className={cn("ui-select-menu", menuClassName)}>
        {showSearch && (
          <div className="relative p-1 pb-1.5">
            <Search className="pointer-events-none absolute start-3 top-1/2 size-3.5 -translate-y-[60%] text-muted-foreground" aria-hidden />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={direction === "rtl" ? "ابحث…" : "Search…"}
              aria-label={direction === "rtl" ? "تصفية الخيارات" : "Filter options"}
              className="h-8 ps-8 text-xs"
              // Typing stays in the field; the menu's typeahead would otherwise move the highlight.
              onKeyDown={(event) => event.stopPropagation()}
            />
          </div>
        )}
        <DropdownMenuRadioGroup value={value} onValueChange={onValueChange}>
          {filtered.length === 0 && (
            <div className="px-3 py-3 text-center text-xs text-muted-foreground">{direction === "rtl" ? "لا توجد نتائج" : "No results"}</div>
          )}
          {filtered.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value} disabled={option.disabled}>
              {option.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
