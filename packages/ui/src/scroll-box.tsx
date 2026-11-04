"use client";

/* eslint jsx-a11y/no-noninteractive-tabindex: "error", jsx-a11y/no-noninteractive-element-interactions: "error" */
/* eslint-disable jsx-a11y/no-noninteractive-tabindex -- WCAG keyboard access to this named overflow viewport requires a tab stop. */

import * as React from "react";
import { cn } from "./utils";

/** Which edges of a scroll area have more rows past them. */
export type ScrollEdge = "none" | "top" | "bottom" | "both";

/** The box's vertical edges with rows past them, and whether rows also run past its side. */
function useScrollEdges(area: HTMLElement | null, list: HTMLElement | null): { edge: ScrollEdge; wide: boolean } {
  const [state, setState] = React.useState<{ edge: ScrollEdge; wide: boolean }>({ edge: "none", wide: false });
  React.useEffect(() => {
    if (!area || !list || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const top = area.scrollTop > 2;
      const bottom = area.scrollTop + area.clientHeight < area.scrollHeight - 2;
      const edge = top && bottom ? "both" : top ? "top" : bottom ? "bottom" : "none";
      const wide = area.scrollWidth > area.clientWidth + 2;
      setState((was) => (was.edge === edge && was.wide === wide ? was : { edge, wide }));
    };
    area.addEventListener("scroll", measure, { passive: true });
    // The first measure comes with the observer's first report, the next ones as the box or its list changes size.
    const sizes = new ResizeObserver(measure);
    sizes.observe(area);
    sizes.observe(list);
    return () => {
      area.removeEventListener("scroll", measure);
      sizes.disconnect();
    };
  }, [area, list]);
  return state;
}

/** Where a key moves the focused box ([down, across]); null for any other key. */
function scrollStep(key: string, area: HTMLElement): [number, number] | null {
  switch (key) {
    case "ArrowDown":
      return [80, 0];
    case "ArrowUp":
      return [-80, 0];
    case "PageDown":
      return [area.clientHeight * 0.9, 0];
    case "PageUp":
      return [-area.clientHeight * 0.9, 0];
    case "End":
      return [area.scrollHeight, 0];
    case "Home":
      return [-area.scrollHeight, 0];
    case "ArrowRight":
      return [0, 80];
    case "ArrowLeft":
      return [0, -80];
    default:
      return null;
  }
}

/** Whether the box can still move that way (a key that cannot is left to the page). */
export function canScrollBoxMove(area: HTMLElement, [down, across]: [number, number]): boolean {
  if (down > 0) return area.scrollTop + area.clientHeight < area.scrollHeight - 1;
  if (down < 0) return area.scrollTop > 0;
  // RTL engines expose negative physical offsets: arrows still move physically.
  if (getComputedStyle(area).direction === 'rtl') {
    return across > 0 ? area.scrollLeft < -1 : area.scrollLeft > area.clientWidth - area.scrollWidth + 1;
  }
  if (across > 0) return area.scrollLeft + area.clientWidth < area.scrollWidth - 1;
  return area.scrollLeft > 0;
}

/**
 * A list inside a box on a page shows a fixed number of rows and scrolls inside the box,
 * so the page never grows with the data (the captain, 2026-10-18, decisions register).
 * Each section sets the box's height (--scroll-box-max, styles/ui.css). The prototype's
 * box edge: a flat hairline where more rows wait, never a fade. While rows wait past an
 * edge (or a wide table runs past its side) the box is a named region and a tab stop that
 * scrolls with the arrow, page, Home and End keys; a list that fits is no stop on the way.
 * A key that cannot move the box further is left to the page, so nothing is trapped.
 */
export function ScrollBox({ label, className, style, children }: { label: string; className?: string; style?: React.CSSProperties; children: React.ReactNode }) {
  const [area, setArea] = React.useState<HTMLDivElement | null>(null);
  const [list, setList] = React.useState<HTMLDivElement | null>(null);
  const { edge, wide } = useScrollEdges(area, list);
  const scrolls = edge !== "none" || wide;
  return (
    // A region is not a button: the keys only scroll what the box holds.
    <div
      ref={setArea}
      className={cn("ui-scroll-box", className)}
      style={style}
      data-edge={edge}
      role={scrolls ? "region" : undefined}
      aria-label={scrolls ? label : undefined}
      tabIndex={scrolls ? 0 : undefined}
      onKeyDown={(e) => {
        // Mobile WebKit does not scroll a focused region with the keys by itself.
        if (e.target !== e.currentTarget || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
        const box = e.currentTarget;
        const step = scrollStep(e.key, box);
        if (step === null || !canScrollBoxMove(box, step)) return;
        e.preventDefault();
        box.scrollBy({ top: step[0], left: step[1] });
      }}
    >
      <div ref={setList} className="ui-scroll-box-list">
        {children}
      </div>
    </div>
  );
}
