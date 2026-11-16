"use client";

import * as React from "react";
import { prefersReducedMotion, readMotionToken } from "./motion-tokens";
import { cn } from "./utils";

/**
 * AnimatedList - the ONE list-transition layer (ADR-0033).
 *
 * Insertions, removals and reorders on list pages used to
 * re-render plain mapped arrays and snap while the control that drove them
 * animated. This primitive gives each keyed row a `.pg-list-item` box and
 * drives three behaviours from styles/motion.css on the existing ladder rungs:
 *
 * - ENTER: only a row the caller marks as a live arrival enters. A key that mounts after the list's first render, or comes back
 *   while its exit still plays, asks the caller's `enters`, told whether the
 *   list has shown that key before; a yes gives its box `data-list-enter`
 *   and CSS plays `pg-listIn` (opacity 0 -> 1, translateY(4px) -> none) on
 *   the image-reveal step, every arrival of a batch at once. Without
 *   `enters`, every row shows at once: the first load, a page added by
 *   scrolling, a filter, a tab switch and a remount.
 *   Zero JavaScript: the attribute is a render-time fact of the key.
 * - EXIT: a removed key keeps its box for one exit beat with
 *   `data-list-exit` (`pg-listOut` on the fast step, pointer-events off) and
 *   unmounts on `animationend` (a bounded timer backs the event up). A full
 *   replacement (no key survives, as when paging) swaps atomically instead.
 * - REORDER: when the key order changes, rows that moved get a FLIP - the
 *   inverse transform is applied without a transition, then released on the
 *   popover step (`data-list-flip`). Only `transform` and `opacity` animate.
 *
 * Reduced motion: the global baseline zeroes the CSS durations and this file
 * skips the exit hold and the FLIP entirely, so rows mount and unmount
 * atomically. The wrapper is a plain block so row margins collapse through it
 * as before; pass `grid` for a card grid, where the wrapper becomes a grid so
 * the card stretches to the row height as a direct grid child would.
 */

export type ListKey = string | number;

type Entry<T> = { key: ListKey; item: T };
type Rendered<T> = Entry<T> & { exiting: boolean };

/** Backstop when an exit keyframe never reports (detached node, engine quirk). */
const EXIT_BACKSTOP_MS = 400;
const FLIP_BACKSTOP_MS = 600;

/**
 * Merge the previously rendered order with the next items so an exiting row
 * keeps its place while it fades instead of collapsing to the end. Pure.
 */
export function mergeOrder<T>(
  previous: readonly ListKey[],
  next: readonly Entry<T>[],
  exiting: ReadonlyMap<ListKey, T>,
): Rendered<T>[] {
  const nextKeys = new Set(next.map((entry) => entry.key));
  const emitted = new Set<ListKey>();
  const out: Rendered<T>[] = [];
  let cursor = 0;
  const flushUntil = (stop: ListKey | null) => {
    while (cursor < next.length) {
      const entry = next[cursor++];
      if (emitted.has(entry.key)) continue;
      out.push({ key: entry.key, item: entry.item, exiting: false });
      emitted.add(entry.key);
      if (entry.key === stop) return;
    }
  };
  for (const key of previous) {
    if (emitted.has(key)) continue;
    if (!nextKeys.has(key)) {
      const held = exiting.get(key);
      if (held !== undefined) {
        out.push({ key, item: held, exiting: true });
        emitted.add(key);
      }
      continue;
    }
    flushUntil(key);
  }
  flushUntil(null);
  return out;
}

/** Everything the render needs, derived from the previous render (state, not
 *  refs, so the render stays pure and the running keyframes stay stable). */
type Snapshot<T> = {
  items: readonly T[];
  order: ListKey[];
  byKey: Map<ListKey, T>;
  exiting: Map<ListKey, T>;
  /** Every key the list has shown, and whether its latest box plays the entrance. */
  seen: Map<ListKey, boolean>;
};

function snapshotFrom<T>(items: readonly T[], getKey: (item: T) => ListKey): Snapshot<T> {
  const byKey = new Map<ListKey, T>();
  const order: ListKey[] = [];
  const seen = new Map<ListKey, boolean>();
  for (const item of items) {
    const key = getKey(item);
    byKey.set(key, item);
    order.push(key);
    seen.set(key, false);
  }
  return { items, order, byKey, exiting: new Map(), seen };
}

function deriveSnapshot<T>(
  previous: Snapshot<T>,
  items: readonly T[],
  getKey: (item: T) => ListKey,
  enters: ((item: T, shownBefore: boolean) => boolean) | undefined,
): Snapshot<T> {
  const next: Entry<T>[] = items.map((item) => ({ key: getKey(item), item }));
  const nextKeys = new Set(next.map((entry) => entry.key));
  const reduced = prefersReducedMotion();
  // A full replacement (paging, a disjoint result set) swaps atomically: an
  // exit hold would stack the old page above the new one for a beat. The hold
  // is for rows leaving a list that otherwise persists.
  const persists = next.length === 0 || (previous.byKey.size === 0 ? previous.exiting.size === 0 : next.some((entry) => previous.byKey.has(entry.key)));
  const exiting = persists ? new Map(previous.exiting) : new Map<ListKey, T>();
  for (const [key, item] of previous.byKey) {
    if (!nextKeys.has(key) && !reduced && persists) exiting.set(key, item);
  }
  for (const key of nextKeys) exiting.delete(key);
  // A box still showing keeps its answer; a key that mounts, or comes back
  // while its exit still plays, asks the caller again.
  const seen = new Map(previous.seen);
  for (const entry of next) {
    if (previous.byKey.has(entry.key)) continue;
    seen.set(entry.key, enters?.(entry.item, previous.seen.has(entry.key)) === true);
  }
  return {
    items,
    order: mergeOrder(previous.order, next, exiting).map((entry) => entry.key),
    byKey: new Map(next.map((entry) => [entry.key, entry.item])),
    exiting,
    seen,
  };
}

export function AnimatedList<T>({
  items,
  getKey,
  children: renderItem,
  as = "div",
  grid = false,
  className,
  empty,
  enters,
  ...rest
}: Omit<React.ComponentProps<"div">, "children"> & {
  items: readonly T[];
  getKey: (item: T) => ListKey;
  /** Renders one row; the row is placed inside the `.pg-list-item` box. */
  children: (item: T, index: number) => React.ReactNode;
  as?: "div" | "section";
  /** The container is a card grid: each box stretches its card to the row. */
  grid?: boolean;
  empty?: React.ReactNode;
  /** Asked when a key mounts after the list's first render or comes back
   *  while its exit still plays (and told whether the list has shown it
   *  before): should this row enter? Without it no row enters. */
  enters?: (item: T, shownBefore: boolean) => boolean;
}) {
  const [snapshot, setSnapshot] = React.useState<Snapshot<T>>(() => snapshotFrom(items, getKey));

  // The React "information from previous renders" pattern: when the items
  // change, derive the next snapshot during render so a removed key is kept as
  // exiting in the SAME commit and never unmounts for a frame first.
  if (snapshot.items !== items) {
    setSnapshot(deriveSnapshot(snapshot, items, getKey, enters));
  }

  const rendered: Rendered<T>[] = snapshot.order.map((key) => {
    const held = snapshot.exiting.get(key);
    return held !== undefined
      ? { key, item: held, exiting: true }
      : { key, item: snapshot.byKey.get(key) as T, exiting: false };
  });

  const container = React.useRef<HTMLElement | null>(null);
  const nodes = React.useRef(new Map<ListKey, HTMLDivElement>());
  const rects = React.useRef(new Map<ListKey, { x: number; y: number }>());
  const lastLayout = React.useRef<{ signature: string; width: number } | null>(null);
  const timers = React.useRef(new Map<ListKey, number>());

  const setContainer = React.useCallback((node: HTMLElement | null) => {
    container.current = node;
  }, []);

  const settle = React.useCallback((key: ListKey) => {
    const timer = timers.current.get(key);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      timers.current.delete(key);
    }
    setSnapshot((current) => {
      if (!current.exiting.has(key)) return current;
      const exiting = new Map(current.exiting);
      exiting.delete(key);
      return { ...current, exiting, order: current.order.filter((candidate) => candidate !== key) };
    });
  }, []);

  // Exit backstop timers: one per exiting key, cleared when the keyframe reports.
  React.useEffect(() => {
    for (const key of snapshot.exiting.keys()) {
      if (timers.current.has(key)) continue;
      const exit = readMotionToken("--ds-motion-fast") ?? 150;
      timers.current.set(key, window.setTimeout(() => settle(key), exit + EXIT_BACKSTOP_MS));
    }
  }, [snapshot.exiting, settle]);
  React.useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const timer of pending.values()) window.clearTimeout(timer);
      pending.clear();
    };
  }, []);

  // FLIP: measure every commit; animate only when the key order changed and
  // the container kept its width (a resize or layout switch snaps instead).
  const signature = JSON.stringify(snapshot.order);
  React.useLayoutEffect(() => {
    const root = container.current;
    if (!root) return;
    const origin = root.getBoundingClientRect();
    const next = new Map<ListKey, { x: number; y: number }>();
    for (const [key, node] of nodes.current) {
      const box = node.getBoundingClientRect();
      next.set(key, { x: box.left - origin.left, y: box.top - origin.top });
    }
    const previous = lastLayout.current;
    const orderChanged = previous !== null && previous.signature !== signature;
    const sameWidth = previous !== null && Math.abs(previous.width - origin.width) < 1;
    let frame: number | undefined;
    if (orderChanged && sameWidth && !prefersReducedMotion()) {
      const moved: HTMLDivElement[] = [];
      for (const [key, node] of nodes.current) {
        const before = rects.current.get(key);
        const after = next.get(key);
        if (!before || !after || node.hasAttribute("data-list-exit")) continue;
        const dx = before.x - after.x;
        const dy = before.y - after.y;
        if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) continue;
        node.removeAttribute("data-list-flip");
        node.style.transform = `translate(${dx}px, ${dy}px)`;
        moved.push(node);
      }
      if (moved.length) {
        // Commit the inverse transform before releasing it on the next frame.
        void root.offsetWidth;
        frame = window.requestAnimationFrame(() => {
          for (const node of moved) {
            node.setAttribute("data-list-flip", "");
            node.style.transform = "";
            const backstop = window.setTimeout(() => node.removeAttribute("data-list-flip"), FLIP_BACKSTOP_MS);
            node.addEventListener(
              "transitionend",
              () => {
                window.clearTimeout(backstop);
                node.removeAttribute("data-list-flip");
              },
              { once: true },
            );
          }
        });
      }
    }
    rects.current = next;
    lastLayout.current = { signature, width: origin.width };
    return () => {
      if (frame !== undefined) window.cancelAnimationFrame(frame);
    };
  }, [signature]);

  const body = rendered.map((entry, index) => (
    <div
      key={entry.key}
      ref={(node) => {
        if (node) nodes.current.set(entry.key, node);
        else nodes.current.delete(entry.key);
      }}
      className="pg-list-item"
      data-list-enter={snapshot.seen.get(entry.key) ? "" : undefined}
      data-list-exit={entry.exiting ? "" : undefined}
      inert={entry.exiting ? true : undefined}
      aria-hidden={entry.exiting ? true : undefined}
      onAnimationEnd={(event) => {
        if (event.target === event.currentTarget && event.animationName === "pg-listOut") settle(entry.key);
      }}
    >
      {renderItem(entry.item, index)}
    </div>
  ));
  const classes = cn("pg-list", grid && "pg-list-grid", className);
  const content = body.length ? body : empty ? <div className={cn(grid && "col-span-full")}>{empty}</div> : null;

  return as === "section" ? (
    <section {...rest} ref={setContainer} className={classes}>
      {content}
    </section>
  ) : (
    <div {...rest} ref={setContainer} className={classes}>
      {content}
    </div>
  );
}
