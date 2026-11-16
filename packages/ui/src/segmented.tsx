"use client";

import * as React from "react";
import { cn } from "./utils";
import type { SwitchHue } from "./switch-hue";
import { useSegmentedThumb } from "./segmented-thumb";

/**
 * Segmented - the ONE selected-control idiom (ADR-0033): a `pg-toggle` group
 * whose active option is painted by a single shared thumb that SLIDES between
 * options on the popover step with the settle curve, the same rung and curve
 * as the view-switch knob. Every single-choice toggle in the app renders
 * through this file so the product has one behaviour and one timing.
 *
 * The thumb is CSS-driven (web/styles/controls.css `.pg-seg-thumb`): the group
 * measures the active option after layout and hands the geometry over as
 * custom properties, the transform transition does the rest. No animation
 * runtime ships with a list route (the bundle lever the previous spring thumb
 * paid for), and the global reduced-motion baseline turns the slide into an
 * instant jump for free.
 *
 * Before the first measurement (server HTML, pre-hydration paint) the active
 * option paints its own fill, so there is never a flash of an unfilled state.
 *
 * Two shapes:
 * - `Segmented` - the options API used by almost every call site.
 * - `SegmentedGroup` + `SegmentedItem` - the composable pair for a bar that
 *   carries extra controls next to its options (a saved-view
 *   toolbar). Exactly one descendant carries `data-seg-active`; the group
 *   measures it.
 *
 * Callers own route transitions and any cross-page selection state.
 */

export function SegmentedGroup({
  activeKey,
  compact = false,
  className,
  children,
  role = "group",
  ...rest
}: React.ComponentProps<"div"> & {
  /** Identity of the active option; a change re-measures the thumb. */
  activeKey: string | number | null;
  compact?: boolean;
}) {
  const { ref, measured, thumb } = useSegmentedThumb(activeKey, [compact, children]);

  return (
    <div
      ref={ref}
      role={role}
      data-seg-measured={measured ? "" : undefined}
      className={cn("pg-toggle pg-seg", compact && "pg-toggle-compact", className)}
      {...rest}
    >
      {thumb}
      {children}
    </div>
  );
}

export function SegmentedItem({
  active,
  hue,
  plain,
  className,
  children,
  ...rest
}: React.ComponentProps<"button"> & {
  active: boolean;
  /** The option's meaning in the calm colour code (lib/switch-hue.ts) when its label is
   *  not plain text: its words take that tone. */
  hue?: SwitchHue;
  /** The label is free text such as a person's name, never a status word: it is not
   * looked up in the colour code, so a teammate called "Active" stays in plain ink. */
  plain?: boolean;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      data-seg-active={active ? "" : undefined}
      data-hue={hue}
      data-label={!plain && typeof children == "string" ? children : undefined}
      className={cn(
        "pg-toggle-item pg-seg-item",
        active ? "pg-seg-item-active" : "pg-toggle-item-inactive",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

export interface SegmentedOption<T extends string> {
  value: T;
  /** Visible content; an icon-only option names itself through `aria-label`. */
  label: React.ReactNode;
  "aria-label"?: string;
  /** The option's meaning when its label is not plain text; a text label is looked up
   *  by the stylesheet (lib/switch-hue.ts). */
  hue?: SwitchHue;
  /** Free text such as a person's name: never coloured (see SegmentedItem). */
  plain?: boolean;
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  compact = false,
  className,
  itemClassName,
  "aria-label": ariaLabel,
  "data-arrive": arrive,
}: {
  value: T;
  onChange: (next: T) => void;
  options: readonly SegmentedOption<T>[];
  compact?: boolean;
  className?: string;
  itemClassName?: string;
  "aria-label"?: string;
  "data-arrive"?: "within";
}) {
  return (
    <SegmentedGroup activeKey={value} compact={compact} className={className} aria-label={ariaLabel} data-arrive={arrive}>
      {options.map((option) => (
        <SegmentedItem
          key={option.value}
          active={option.value === value}
          onClick={() => onChange(option.value)}
          aria-label={option["aria-label"]}
          hue={option.hue}
          plain={option.plain}
          className={itemClassName}
        >
          {option.label}
        </SegmentedItem>
      ))}
    </SegmentedGroup>
  );
}
