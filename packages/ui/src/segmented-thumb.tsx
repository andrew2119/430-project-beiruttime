"use client";

import * as React from "react";

type ThumbRect = { x: number; y: number; w: number; h: number };

const sameRect = (a: ThumbRect | null, b: ThumbRect) =>
  a !== null && a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h;

/**
 * The shared thumb's measuring: the element carrying `data-seg-active` inside the
 * returned ref is measured after layout, and again when fonts, a resize or a
 * re-flow move it. `thumb` is the key to render first inside that element (null
 * until measured). SegmentedGroup (segmented.tsx) draws through it, and so do the
 * page header's round view pills (web/shell/page-header.tsx). It
 * is its own module so the header takes the measuring without the whole Segmented.
 */
export function useSegmentedThumb(activeKey: string | number | null, deps: unknown) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [rect, setRect] = React.useState<ThumbRect | null>(null);

  const measure = React.useCallback(() => {
    const group = ref.current;
    if (!group) return;
    const active = group.querySelector<HTMLElement>("[data-seg-active]");
    if (!active) {
      setRect(null);
      return;
    }
    const next = {
      x: active.offsetLeft,
      y: active.offsetTop,
      w: active.offsetWidth,
      h: active.offsetHeight,
    };
    setRect((current) => (sameRect(current, next) ? current : next));
  }, []);

  // Re-measure whenever the active option, density or option labels change
  // (children is a fresh array each render; setRect bails when nothing moved).
  React.useLayoutEffect(measure, [measure, activeKey, deps]);

  // Fonts loading, a resize or a flex re-distribution move the options
  // without a React render: follow the group and the active option.
  React.useEffect(() => {
    const group = ref.current;
    if (!group || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(group);
    const active = group.querySelector("[data-seg-active]");
    if (active) observer.observe(active);
    return () => observer.disconnect();
  }, [measure, activeKey]);

  const thumb = rect && (
    <span
      aria-hidden
      className="pg-seg-thumb"
      style={
        {
          "--pg-seg-x": `${rect.x}px`,
          "--pg-seg-y": `${rect.y}px`,
          "--pg-seg-w": `${rect.w}px`,
          "--pg-seg-h": `${rect.h}px`,
        } as React.CSSProperties
      }
    />
  );
  return { ref, measured: rect !== null, thumb };
}
