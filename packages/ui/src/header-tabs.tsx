"use client";
/* Shared page-header tabs. Pane is the active look; alternate looks remain unused.
 *
 *   A "Tray"   - the tabs sit in one recessed track and a raised key glides between
 *                them: the same language as the site's Segmented mode switches.
 *   B "Ink"    - free-standing labels; the current tab is a solid ink plate that
 *                stretches across (its leading edge first), revealing the labels in
 *                light ink exactly where it covers them; a soft ghost follows the
 *                mouse. The header's mode switches take the same ink key.
 *   C "Folder" - the tabs stand in a recessed band on the card's bottom edge; the
 *                current tab is a sheet of the page below, joined to it with curved
 *                feet, that slides along the band.
 *
 * One moving piece per look (the key, the plate, the sheet), measured from the
 * current tab after layout (the Segmented thumb's technique), so the motion never
 * remounts or jumps. The lab bar's "Tabs" switch (id `tabs`) picks the look; the
 * pick also lands on the html element (`data-lab-tabs`) so the header's mode
 * switches can follow it. Reduced motion: every move is instant.
 *
 * Phones: a tab row that does not fit on one line (measured, never guessed: an
 * invisible single-line copy is compared with the room) turns into tiles with the
 * icon over the label, all side by side, so the current tab is never scrolled away.
 *
 * Semantics are unchanged from the header's tabs: navigation tabs are links (or
 * buttons) marked aria-current="page"; a non-navigation row is a tablist of tabs
 * marked aria-selected. Counts and icons stay.
 *
 * Liquid glass reduces contrast between the current tab and its neighbors.
 * Tray, Ink and Folder remain in the code and stylesheet, unused:
 *
 *   A "Frost" - a milky frosted key raised out of a sunken glass track; glides.
 *   B "Lens"  - Ink's free labels and stretching key, as a clear lens: the labels it
 *               passes over show through it slightly magnified and bent at its rim
 *               (an SVG displacement filter built from flat floods and a blur).
 *   C "Pane"  - the whole row is a floating glass capsule; the current tab is a pane
 *               of smoked glass inside it that glides and settles with a small give.
 *
 * Glass is translucency, backdrop blur and saturation, a thin light inner edge and a
 * soft shadow: no gradients. The header's mode switches and the detail
 * switcher take the same glass. Phones (coarse pointers) keep the look without the
 * live blur and bending, so scrolling never pays for them. */
import * as React from "react";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";

export type TabsLook = "A" | "B" | "C";
export const TAB_LOOKS: [TabsLook, string][] = [
  ["A", "Tray"],
  ["B", "Ink"],
  ["C", "Folder"],
];
const LOOK_IDS = TAB_LOOKS.map(([v]) => v);

/** Round 2: the three liquid glass takes on the lab bar's "Tabs" switch. Their looks
 *  are named (frost, lens, pane) so the first round's A/B/C rules stay untouched. */
export type GlassLook = "frost" | "lens" | "pane";
export const GLASS_LOOKS: [string, string][] = [
  ["A", "Frost"],
  ["B", "Lens"],
  ["C", "Pane"],
];
const GLASS_BY_PICK: Record<string, GlassLook> = { A: "frost", B: "lens", C: "pane" };
const GLASS_IDS = GLASS_LOOKS.map(([v]) => v);

/** The lab's current tabs look (lab bar switch id "tabs"). The first round's looks
 *  (Tray, Ink, Folder; Ink was locked on 2026-10-02 evening) are kept, unused. */
export function useTabsLook(): TabsLook | GlassLook {
  // Pane uses rounded rectangles, not capsules. Alternate looks remain unused.
  void LOOK_IDS;
  void GLASS_IDS;
  return GLASS_BY_PICK.C;
}

/** Lens: the displacement map is built from flat floods (neutral grey, and a strip
 *  per edge that pushes outward), softened by a blur, all relative to the lens box,
 *  so the labels bend only at the rim and stay crisp in the middle. The flood values
 *  are filter data (128 = no displacement), not colours anyone sees. */
function LensFilter({ id }: { id: string }) {
  return (
    <svg className="hx-lens-defs" width="0" height="0" aria-hidden focusable="false">
      <filter id={id} x="0" y="0" width="1" height="1" primitiveUnits="objectBoundingBox" colorInterpolationFilters="sRGB">
        <feFlood floodColor="rgb(128,128,128)" result="base" />
        <feFlood floodColor="rgb(196,128,128)" x="0" y="0" width="0.12" height="1" result="left" />
        <feFlood floodColor="rgb(60,128,128)" x="0.88" y="0" width="0.12" height="1" result="right" />
        <feFlood floodColor="rgb(128,180,128)" x="0" y="0" width="1" height="0.2" result="top" />
        <feFlood floodColor="rgb(128,76,128)" x="0" y="0.8" width="1" height="0.2" result="bottom" />
        <feMerge result="map0">
          <feMergeNode in="base" />
          <feMergeNode in="top" />
          <feMergeNode in="bottom" />
          <feMergeNode in="left" />
          <feMergeNode in="right" />
        </feMerge>
        <feGaussianBlur in="map0" stdDeviation="0.05 0.14" result="map" />
        <feDisplacementMap in="SourceGraphic" in2="map" scale="0.05" xChannelSelector="R" yChannelSelector="G" />
      </filter>
    </svg>
  );
}

export type HeaderTabItem = {
  id: string;
  label: string;
  icon?: LucideIcon;
  count?: React.ReactNode;
  /** A status tone (a dot before the label). */
  tone?: string;
  /** A real prefetched link, preserving page-owned navigation. */
  href?: string;
};

type Rect = { x: number; y: number; w: number; h: number; r: number };
const same = (a: Rect | null, b: Rect | null) =>
  !!a && !!b && a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h && a.r === b.r;

/* Only the first header with tabs on a page puts the switch in the lab bar. */
const owners: number[] = [];
const ownerListeners = new Set<() => void>();
const subscribeOwners = (l: () => void) => {
  ownerListeners.add(l);
  return () => {
    ownerListeners.delete(l);
  };
};
let nextOwner = 1;
function useSwitchOwner() {
  const [id] = React.useState(() => nextOwner++);
  const first = React.useSyncExternalStore(
    subscribeOwners,
    () => owners[0] === id,
    () => false,
  );
  React.useEffect(() => {
    owners.push(id);
    ownerListeners.forEach((l) => l());
    return () => {
      owners.splice(owners.indexOf(id), 1);
      ownerListeners.forEach((l) => l());
    };
  }, [id]);
  return first;
}

const prefersReduced = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function TabInner({ it }: { it: HeaderTabItem }) {
  const Icon = it.icon;
  return (
    <>
      {Icon && <Icon aria-hidden />}
      {it.tone && <span className="hx-tab-dot" style={{ color: it.tone }} aria-hidden />}
      {/* data-text reserves the bold width, so the row never shifts when the
          current tab's label turns heavier. */}
      <span className="hx-tab-label" data-text={it.label}>
        {it.label}
      </span>
      {it.count != null && <span className="hx-tab-count">{it.count}</span>}
    </>
  );
}

export function HeaderTabs({
  items,
  value,
  onChange,
  label,
  nav,
}: {
  items: HeaderTabItem[];
  value: string;
  onChange: (id: string) => void;
  label: string;
  nav?: boolean;
}) {
  const look = useTabsLook();
  const owner = useSwitchOwner();
  const lensId = `hx-lens-${React.useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  // Ink and Lens: a label copy rides inside the key; Ink and Lens also get the ghost.
  const carries = look === "B" || look === "lens";
  const ref = React.useRef<HTMLDivElement>(null);
  const ruler = React.useRef<HTMLDivElement>(null);
  const last = React.useRef<Rect | null>(null);
  const [ind, setInd] = React.useState<{ rect: Rect; dir?: "fwd" | "back" } | null>(null);
  const [fit, setFit] = React.useState<"line" | "stack">("line");
  const [ghost, setGhost] = React.useState<{ rect: Rect; on: boolean } | null>(null);

  // The pick also styles the header's mode switches (look B inks their key).
  React.useEffect(() => {
    document.documentElement.dataset.labTabs = look;
  }, [look]);

  const rectOf = React.useCallback((el: HTMLElement, t: HTMLElement): Rect => {
    const x = t.offsetLeft;
    const w = t.offsetWidth;
    return { x, y: t.offsetTop, w, h: t.offsetHeight, r: el.clientWidth - x - w };
  }, []);

  /** The moving piece follows the current tab (and its direction of travel). */
  const measure = React.useCallback(() => {
    const el = ref.current;
    const a = el?.querySelector<HTMLElement>(":scope > .hx-tab[data-on]");
    if (!el || !a || el.clientWidth === 0) {
      if (el && !a) {
        last.current = null;
        setInd(null);
      }
      return;
    }
    const next = rectOf(el, a);
    if (same(last.current, next)) return;
    const prev = last.current;
    last.current = next;
    const dir = prev && next.x !== prev.x ? (next.x > prev.x ? "fwd" : "back") : undefined;
    setInd((cur) => ({ rect: next, dir: dir ?? cur?.dir }));
  }, [rectOf]);

  /** One line when every tab fits with its label beside its icon; tiles otherwise. */
  const checkFit = React.useCallback(() => {
    const el = ref.current;
    const r = ruler.current;
    if (!el || !r || el.clientWidth === 0) return;
    setFit(r.offsetWidth > el.clientWidth + 0.5 ? "stack" : "line");
  }, []);

  // The tabs' identity (ids, labels, counts as text): a page re-renders with a fresh
  // items array every time, so the effects key on this instead.
  const shape = items.map((it) => `${it.id}:${it.label}`).join("|");

  React.useLayoutEffect(() => {
    checkFit();
    measure();
  });

  React.useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      checkFit();
      measure();
    });
    ro.observe(el);
    if (ruler.current) ro.observe(ruler.current);
    el.querySelectorAll(":scope > .hx-tab").forEach((t) => ro.observe(t));
    const fonts = document.fonts;
    const again = () => {
      checkFit();
      measure();
    };
    fonts?.addEventListener?.("loadingdone", again);
    return () => {
      ro.disconnect();
      fonts?.removeEventListener?.("loadingdone", again);
    };
  }, [checkFit, measure, shape, look]);

  // A row wider than its room (many tabs on a narrow screen) keeps the current
  // tab in view.
  React.useEffect(() => {
    const el = ref.current;
    const a = el?.querySelector<HTMLElement>(":scope > .hx-tab[data-on]");
    if (!el || !a || el.scrollWidth <= el.clientWidth + 1) return;
    el.scrollTo({ left: a.offsetLeft - (el.clientWidth - a.offsetWidth) / 2, behavior: prefersReduced() ? "auto" : "smooth" });
  }, [value, fit]);

  // Look B: a soft ghost glides to the tab under the mouse. It first lands, unseen,
  // on the tab the mouse came in on and fades in there (no slide from elsewhere).
  const ghostOn = React.useRef(false);
  const onOver = (e: React.PointerEvent) => {
    if (!carries || e.pointerType !== "mouse") return;
    const el = ref.current;
    const t = (e.target as Element).closest<HTMLElement>(".hx-tab");
    if (!el || !t || !el.contains(t)) return;
    const rect = rectOf(el, t);
    if (ghostOn.current) {
      setGhost({ rect, on: true });
      return;
    }
    ghostOn.current = true;
    setGhost({ rect, on: false });
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        if (ghostOn.current) setGhost((g) => (g ? { ...g, on: true } : g));
      }),
    );
  };
  const onLeave = () => {
    ghostOn.current = false;
    setGhost((g) => (g ? { ...g, on: false } : g));
  };

  const vars: Record<string, string> = {};
  if (ind) {
    const { x, y, w, h, r } = ind.rect;
    Object.assign(vars, { "--hx-ind-x": `${x}px`, "--hx-ind-y": `${y}px`, "--hx-ind-w": `${w}px`, "--hx-ind-h": `${h}px`, "--hx-ind-r": `${r}px` });
  }
  if (ghost) {
    const { x, y, w, h } = ghost.rect;
    Object.assign(vars, { "--hx-ghost-x": `${x}px`, "--hx-ghost-y": `${y}px`, "--hx-ghost-w": `${w}px`, "--hx-ghost-h": `${h}px` });
  }

  return (
    <>
      {/* Pane is fixed; no look switch is rendered. */}
      {owner && null}
      {look === "lens" && <LensFilter id={lensId} />}
      <div
        ref={ref}
        className="hx-tabs"
        data-look={look}
        data-fit={fit}
        data-count={items.length}
        data-dir={ind?.dir}
        data-measured={ind ? "" : undefined}
        data-nav={nav || undefined}
        role={nav ? undefined : "tablist"}
        aria-label={label}
        style={vars as React.CSSProperties}
        onPointerOver={onOver}
        onPointerLeave={onLeave}
      >
        {/* The moving pieces paint first, under the labels. */}
        {carries && ghost && <span className="hx-ghost" data-on={ghost.on || undefined} aria-hidden />}
        {ind && (
          <span className="hx-ind" aria-hidden>
            {/* Look B: the plate carries the labels in its own ink colours, held in
                place while it moves, so a label is always light exactly where the
                plate covers it, mid-flight too. */}
            {look === "B" && (
              <span className="hx-tabs hx-ind-copy" data-look="B" data-fit={fit} data-measured="">
                {items.map((it) => (
                  <span key={it.id} className="hx-tab" data-on={it.id === value || undefined}>
                    <TabInner it={it} />
                  </span>
                ))}
              </span>
            )}
            {/* Lens: the same held copy, seen through the glass: slightly magnified
                and bent at the rim by the displacement filter. */}
            {look === "lens" && (
              <span className="hx-lens" style={{ filter: `url(#${lensId})` }}>
                <span className="hx-tabs hx-ind-copy" data-look="lens" data-fit={fit} data-measured="">
                  {items.map((it) => (
                    <span key={it.id} className="hx-tab" data-on={it.id === value || undefined}>
                      <TabInner it={it} />
                    </span>
                  ))}
                </span>
              </span>
            )}
          </span>
        )}
        {items.map((it) => {
          const on = it.id === value;
          if (it.href) {
            return (
              <Link key={it.id} href={it.href} prefetch className="hx-tab" aria-current={on ? "page" : undefined} data-on={on || undefined}>
                <TabInner it={it} />
              </Link>
            );
          }
          return (
            <button
              key={it.id}
              type="button"
              className="hx-tab"
              role={nav ? undefined : "tab"}
              aria-selected={nav ? undefined : on}
              aria-current={nav && on ? "page" : undefined}
              data-on={on || undefined}
              onClick={() => onChange(it.id)}
              onKeyDown={(event) => {
                if (nav) return;
                const direction = document.documentElement.dir === 'rtl' ? -1 : 1;
                const delta = event.key === 'ArrowRight' ? direction : event.key === 'ArrowLeft' ? -direction : 0;
                if (!delta && event.key !== 'Home' && event.key !== 'End') return;
                event.preventDefault();
                const index = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (items.findIndex(item => item.id === value) + delta + items.length) % items.length;
                onChange(items[index].id);
                ref.current?.querySelectorAll<HTMLButtonElement>(':scope > button.hx-tab')[index]?.focus();
              }}
            >
              <TabInner it={it} />
            </button>
          );
        })}
      </div>
      {/* The fit check: the same tabs on one line, invisible and outside the
          layout (a zero-size box that clips), measured against the row. */}
      <div className="hx-tabs-rulerbox" aria-hidden>
        <div ref={ruler} className="hx-tabs hx-tabs-ruler" data-look={look} data-fit="line">
          {items.map((it) => (
            <span key={it.id} className="hx-tab" data-on={it.id === value || undefined}>
              <TabInner it={it} />
            </span>
          ))}
        </div>
      </div>
    </>
  );
}
