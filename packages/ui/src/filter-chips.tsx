"use client";

import * as React from "react";
import { X } from "lucide-react";
import { AnimatedList } from "./animated-list";
import { cn } from "./utils";

/**
 * FilterChips - the line above a filtered list, from the Studio's Posts filter
 * design: the count, one chip per active filter (each with its own remove),
 * and Clear all, on one fixed-height line (two fixed rows on a phone), so the
 * list below never jumps as filters come and go. Chips enter and leave through
 * the shared AnimatedList; Clear all keeps its place and only fades in while
 * anything narrows the list.
 */

export type FilterChip = { key: string; label: string };

/** The accessible name of a chip's remove button. */
export function chipRemoveLabel(label: string): string {
  return `Remove filter: ${label}`;
}

/** Clear all is offered while a chip is on or something else narrows the list. */
export function isNarrowed(chips: readonly FilterChip[], alsoNarrowed = false): boolean {
  return chips.length > 0 || alsoNarrowed;
}

export function FilterChips({
  chips,
  onRemove,
  onClearAll,
  count,
  alsoNarrowed = false,
  busy = false,
  className,
  labels,
}: {
  labels: { activeFilters: string; clearAll: string; remove: (label: string) => string };
  chips: readonly FilterChip[];
  onRemove: (key: string) => void;
  onClearAll: () => void;
  /** The count on the left, announced politely as it changes. */
  count: React.ReactNode;
  /** Something without a chip (a search box) also narrows the list. */
  alsoNarrowed?: boolean;
  /** A new result is loading while the previous one stays on screen. */
  busy?: boolean;
  className?: string;
}) {
  const narrowed = isNarrowed(chips, alsoNarrowed);
  return (
    <div
      className={cn("ui-filter-line", className)}
      data-narrowed={narrowed ? "" : undefined}
      aria-busy={busy || undefined}
    >
      <p className="ui-filter-line-count" aria-live="polite">
        {count}
      </p>
      <AnimatedList
        items={chips}
        getKey={(chip) => chip.key}
        className="ui-filter-chips"
        role="group"
        aria-label={labels.activeFilters}
      >
        {(chip) => (
          <span className="ui-filter-chip">
            {chip.label}
            <button
              type="button"
              className="ui-filter-chip-x"
              aria-label={labels.remove(chip.label)}
              onClick={() => onRemove(chip.key)}
            >
              <X aria-hidden />
            </button>
          </span>
        )}
      </AnimatedList>
      <button
        type="button"
        className="ui-filter-link ui-filter-clear"
        data-show={narrowed ? "" : undefined}
        tabIndex={narrowed ? 0 : -1}
        aria-hidden={!narrowed}
        onClick={onClearAll}
      >
        {labels.clearAll}
      </button>
    </div>
  );
}
