"use client";
/* Shared sticky page headers stay visible while their content scrolls.
 *
 * One small observer per page header (mounted by PageHeader and PageToolbar). It finds
 * the box that can stick (the header's outermost wrapper inside the page), marks it,
 * and measures the header once per layout change into a few CSS custom properties.
 * Everything that moves is CSS (web/styles/sticky.css): sticky positioning plus one
 * scroll-linked timeline on the tray, so scrolling never runs script and the page
 * never reflows (the header keeps its full height in the page at all times).
 *
 * B "Condense" is fixed: a solid fold with a crisp top and clean lower edge.
 * The title, actions and tabs never fade. The fold follows scroll position
 * frame by frame. Progress p = how far the page has scrolled / how
 * much the card can shrink, so the card's bottom edge rides on the page and it opens
 * exactly as you scroll back up. Browsers with scroll-driven animations run p on the
 * tray's scroll timeline (no script while scrolling); elsewhere one passive scroll
 * listener writes p in the same frame. Reduced motion: no in-between, the card sits
 * open or condensed. The card's open height stays reserved, so the page never
 * reflows.
 *
 * A "Whole card" and C "Controls only" (C: the title area slides away under the
 * card's top edge, the controls stay, a detail tab's toolbar pins under them) stay
 * in the code, unused.
 *
 * Measured, never guessed: both states are read from the layout in one synchronous
 * pass with motion switched off. Its precise natural height stays reserved for the
 * condensed read (see holdRoom; incident 2026-10-11, docs/frontend-quality-law.md).
 * Once measured, the resting reserve is the lab's whole-pixel offsetHeight. */
import * as React from "react";

export type StickyOption = "A" | "B" | "C";
export const STICKY_OPTIONS: [StickyOption, string][] = [
  ["A", "Whole card"],
  ["B", "Condense"],
  ["C", "Controls only"],
];
/** B "Condense" is fixed. A and C remain unused. */
const LOCKED: StickyOption = "B";

/* ── one lab-bar switch however many headers are on screen ─────────────────── */

const owners: symbol[] = [];
const ownerSubs = new Set<() => void>();
const ownerNotify = () => ownerSubs.forEach((l) => l());
const ownerSubscribe = (l: () => void) => {
  ownerSubs.add(l);
  return () => ownerSubs.delete(l);
};
/** True for the first page header on screen (it alone shows the lab-bar switch). */
function useIsFirst(enabled: boolean) {
  const me = React.useRef<symbol>(Symbol("sticky"));
  React.useEffect(() => {
    if (!enabled) return;
    const id = me.current;
    owners.push(id);
    ownerNotify();
    return () => {
      const i = owners.indexOf(id);
      if (i >= 0) owners.splice(i, 1);
      ownerNotify();
    };
  }, [enabled]);
  return React.useSyncExternalStore(
    ownerSubscribe,
    () => enabled && owners[0] === me.current,
    () => false,
  );
}

/* ── measuring ───────────────────────────────────────────────────────────── */

const supportsScrollTimeline = () =>
  typeof CSS !== "undefined" && typeof CSS.supports === "function" && CSS.supports("animation-timeline", "scroll()");

/** Layout offset of `el` inside `anc` (a positioned ancestor), ignoring transforms. */
function offsetIn(el: HTMLElement, anc: HTMLElement) {
  let x = 0;
  let y = 0;
  let n: HTMLElement | null = el;
  while (n && n !== anc) {
    x += n.offsetLeft;
    y += n.offsetTop;
    const p = n.offsetParent as HTMLElement | null;
    if (p && p !== anc) {
      x += p.clientLeft;
      y += p.clientTop;
    }
    n = p;
  }
  return n === anc ? { x, y } : null;
}
/** The children of `el` that draw a box, looking through boxless (display: contents)
 *  wrappers (the phone title line lays its pieces out on one grid). */
function boxes(el: HTMLElement): HTMLElement[] {
  return [...el.children].flatMap((c) =>
    c instanceof HTMLElement && getComputedStyle(c).display === "contents" ? boxes(c) : c instanceof HTMLElement ? [c] : [],
  );
}
const shown = (el: Element | null | undefined): el is HTMLElement =>
  !!el && el instanceof HTMLElement && el.offsetParent !== null && el.offsetHeight > 0;

/** The box that sticks: the header's outermost wrapper that holds nothing else (its
 *  parent is taller), skipping boxless (display: contents) wrappers. A toolbar may
 *  sit in a small wrapper of its own (the Posts tab), so it may climb one more. */
function findRoot(wrap: HTMLElement, tray: HTMLElement, toolbar: boolean) {
  let root = wrap;
  let n = wrap.parentElement;
  while (n && n !== tray) {
    if (getComputedStyle(n).display === "contents") {
      n = n.parentElement;
      continue;
    }
    // The box already pinned keeps its open height reserved while the card inside is
    // condensed, so it still counts as the header's own wrapper.
    const pure = n.hasAttribute("data-sx-root") || n.offsetHeight <= root.offsetHeight + 1;
    const snug = toolbar && n.offsetHeight < root.offsetHeight * 2.5 && n.childElementCount <= 3;
    if (!pure && !snug) break;
    root = n;
    n = n.parentElement;
  }
  // The box the root sticks inside: the next real box up.
  let host = root.parentElement;
  while (host && host !== tray && getComputedStyle(host).display === "contents") host = host.parentElement;
  return { root, host };
}

type Vars = Record<string, number>;
/** A piece that fades out while the page scrolls from `from` to `to` (px). */
type Fade = [HTMLElement, number, number];
type Measured = { vars: Vars; stuck: number; fades: Fade[] };

function measureHeader(root: HTMLElement, wrap: HTMLElement, opt: StickyOption): Measured | null {
  const head = wrap.querySelector<HTMLElement>(".hx-head");
  const zone = wrap.querySelector<HTMLElement>(".hx-zone");
  if (!head || !zone) return null;
  const phone = wrap.clientWidth <= 480;
  const H = head.offsetHeight;
  const headAt = offsetIn(head, root)?.y ?? 0;
  const zoneAt = offsetIn(zone, root)?.y ?? 0;
  // The status line and notice under the card: they slide away under it.
  const E = Math.max(0, zone.offsetHeight - (headAt - zoneAt) - H);
  const at = (el: HTMLElement) => offsetIn(el, head) ?? { x: 0, y: 0 };
  const rows = {
    lead: head.querySelector<HTMLElement>(":scope > .hx-lead"),
    title: head.querySelector<HTMLElement>(":scope > .hx-titlerow"),
    views: head.querySelector<HTMLElement>(":scope > .hx-views-row"),
    tools: head.querySelector<HTMLElement>(":scope > .hx-tools-row"),
    nav: head.querySelector<HTMLElement>(":scope > .hx-navrow"),
  };
  const pmode = rows.title?.querySelector<HTMLElement>(":scope > .hx-pmode");
  const slop = phone ? 4 : 0; // the invisible part of a phone control's 44 tap area
  const vars: Vars = { "--sx-d": 0, "--sx-e": E };
  const none: Fade[] = [];

  if (opt === "A") return { vars, stuck: H, fades: none };

  if (opt === "C") {
    const pin = [pmode, rows.views, rows.tools, rows.nav].find(shown);
    let D = 0;
    if (pin) {
      // A bar of controls: 12 above the first one (8 above a phone control, whose
      // 44 box already carries 4 of air), the tabs keep their own 8.
      const air = pin === rows.nav ? 8 : 12 - slop;
      D = at(pin).y - air;
    } else if (shown(rows.lead) && shown(rows.title)) {
      // No controls under the title: the row above it (a back link) scrolls away.
      D = at(rows.title).y - (parseFloat(getComputedStyle(head).paddingTop) || 0);
    }
    D = Math.max(0, Math.round(D));
    // What slides away under the top edge fades as it gets there, so a line of
    // text is never seen sliced in half.
    const leaving = [rows.lead, ...(rows.title ? boxes(rows.title) : [])].filter(
      (el): el is HTMLElement => shown(el) && el !== pmode && el !== pin,
    );
    const fades: Fade[] = leaving
      .map((el): Fade => {
        const y = at(el).y;
        return [el, Math.max(0, y - 8), Math.min(D, y + el.offsetHeight * 0.6)];
      })
      .filter(([, a, b]) => b > a && a < D);
    return { vars: { ...vars, "--sx-d": D }, stuck: H - D, fades };
  }

  // B "Condense" has its own controller (a solid fold, see the hook below).
  return { vars, stuck: H, fades: none };
}

/** Where a box sits in the tray's content when nothing is stuck (a sticky box's own
 *  offsetTop includes how far it is pushed while stuck, so read its neighbours). */
function naturalTop(root: HTMLElement, host: HTMLElement, tray: HTMLElement) {
  const mt = (el: Element) => parseFloat(getComputedStyle(el).marginTop) || 0;
  let prev = root.previousElementSibling as HTMLElement | null;
  while (prev && (!(prev instanceof HTMLElement) || prev.offsetParent === null || getComputedStyle(prev).position === "absolute")) {
    prev = prev.previousElementSibling as HTMLElement | null;
  }
  if (prev) {
    const at = offsetIn(prev, tray);
    if (!at) return null;
    const mb = parseFloat(getComputedStyle(prev).marginBottom) || 0;
    return at.y + prev.offsetHeight + Math.max(mb, mt(root));
  }
  const at = offsetIn(host, tray);
  if (!at) return null;
  return at.y + host.clientTop + (parseFloat(getComputedStyle(host).paddingTop) || 0) + mt(root);
}

/** A detail tab's toolbar (C): it pins under the header's bar with the body card's
 *  own top padding above it, on a strip of the card's paint. */
function measureToolbar(root: HTMLElement, host: HTMLElement, wrap: HTMLElement, tray: HTMLElement): Vars | null {
  const card = wrap.closest<HTMLElement>(".hx-detail-body");
  const body = wrap.querySelector<HTMLElement>(".hx-toolbar-body");
  const hs = parseFloat(tray.style.getPropertyValue("--sx-hs"));
  if (!card || !body || !Number.isFinite(hs)) return null;
  const cs = getComputedStyle(card);
  const pt = parseFloat(cs.paddingTop) || 0;
  const px = parseFloat(cs.paddingLeft) || 0;
  const bh = (offsetIn(body, root)?.y ?? 0) + body.offsetHeight;
  const gap = (parseFloat(getComputedStyle(root).getPropertyValue("--sx-gap")) || 24) + (parseFloat(tray.style.getPropertyValue("--sx-lift")) || 0);
  const nat = naturalTop(root, host, tray);
  if (nat == null) return null;
  return {
    "--sx-tb-pt": pt,
    "--sx-tb-px": px,
    "--sx-tb-bh": bh,
    "--sx-tb-e": Math.max(0, root.offsetHeight - bh),
    "--sx-tb-at": Math.max(0, nat - (gap + hs + pt)),
  };
}

/* ── B "Condense": the solid fold ───────────────────────────────────────── */

/** The pieces that fold away when the card condenses: the row above the title (a
 *  back link), the count line, the phone's mode line, the filters row, the pills when
 *  the page also has tabs, and whatever sits under the card (status line, notice).
 *  The title line (with its actions) and the tabs always stay. Read while open. */
function foldPieces(wrap: HTMLElement): HTMLElement[] {
  const head = wrap.querySelector<HTMLElement>(".hx-head");
  const zone = wrap.querySelector<HTMLElement>(".hx-zone");
  if (!head || !zone) return [];
  const title = head.querySelector<HTMLElement>(":scope > .hx-titlerow");
  const nav = head.querySelector<HTMLElement>(":scope > .hx-navrow");
  const pieces = [
    head.querySelector<HTMLElement>(":scope > .hx-lead"),
    title?.querySelector<HTMLElement>(".hx-count"),
    title?.querySelector<HTMLElement>(":scope > .hx-pmode"),
    head.querySelector<HTMLElement>(":scope > .hx-tools-row"),
    shown(nav) ? head.querySelector<HTMLElement>(":scope > .hx-views-row") : null,
    ...[...zone.children].filter((c) => c !== head),
  ];
  return pieces.filter((el): el is HTMLElement => shown(el));
}

/** The rows that stay and only tighten their spacing: the tabs, or the pills when the
 *  page has no tabs. */
function keptRows(wrap: HTMLElement, folding: HTMLElement[]): HTMLElement[] {
  const head = wrap.querySelector<HTMLElement>(".hx-head");
  if (!head) return [];
  return [head.querySelector<HTMLElement>(":scope > .hx-navrow"), head.querySelector<HTMLElement>(":scope > .hx-views-row")].filter(
    (el): el is HTMLElement => shown(el) && !folding.includes(el),
  );
}

/** The next block of the page's own flow after the header box, if there is one. */
function blockAfter(root: HTMLElement) {
  let next = root.nextElementSibling as HTMLElement | null;
  while (next && (next.offsetParent === null || getComputedStyle(next).position === "absolute")) {
    next = next.nextElementSibling as HTMLElement | null;
  }
  return next;
}

/** The page's own gap under the header box (to its next block), which the solid strip
 *  covers too, so the page passes under a straight edge with the gap kept. */
function gapBelow(root: HTMLElement) {
  const next = blockAfter(root);
  if (!next) return 0;
  const parent = root.parentElement;
  const pcs = parent ? getComputedStyle(parent) : null;
  const flow = pcs && /flex|grid/.test(pcs.display) ? parseFloat(pcs.rowGap) || 0 : 0;
  const mb = parseFloat(getComputedStyle(root).marginBottom) || 0;
  const mt = parseFloat(getComputedStyle(next).marginTop) || 0;
  return flow + (flow ? mb + mt : Math.max(mb, mt));
}

/** A box's used border-box height at layout precision. */
const heightOf = (el: Element) => el.getBoundingClientRect().height;

/** Lends the header box's bottom margin the exact room lost in the condensed layout,
 *  so everything after it stays in place at layout precision. Blocks stacked in plain
 *  flow share one margin, the larger of the box's bottom and the next block's top, so
 *  the loan goes on top of that one; in a flex or grid box the margins stand apart and
 *  it goes on the box's own. Returns the way back. */
function holdRoom(root: HTMLElement, room: number) {
  const parent = root.parentElement;
  const next = parent && !/flex|grid/.test(getComputedStyle(parent).display) ? blockAfter(root) : null;
  const own = parseFloat(getComputedStyle(root).marginBottom) || 0;
  const shared = next ? Math.max(own, parseFloat(getComputedStyle(next).marginTop) || 0) : own;
  const value = root.style.getPropertyValue("margin-block-end");
  const priority = root.style.getPropertyPriority("margin-block-end");
  root.style.setProperty("margin-block-end", `${shared + room}px`, "important");
  return () => {
    if (value) root.style.setProperty("margin-block-end", value, priority);
    else root.style.removeProperty("margin-block-end");
  };
}

/* ── the hook ───────────────────────────────────────────────────────────── */

const UNITLESS = new Set(["--sx-k", "--sx-km"]);
const ALL_VARS = [
  "--sx-d", "--sx-e", "--sx-k", "--sx-km", "--sx-ty-t", "--sx-tx-t", "--sx-ty-m", "--sx-ty-a", "--sx-tx-a", "--sx-ty-k",
  "--sx-tb-pt", "--sx-tb-px", "--sx-tb-bh", "--sx-tb-e", "--sx-tb-at",
];
function setVars(el: HTMLElement, vars: Vars) {
  for (const k of ALL_VARS) if (!(k in vars)) el.style.removeProperty(k);
  for (const [k, v] of Object.entries(vars)) {
    el.style.setProperty(k, UNITLESS.has(k) ? String(Math.round(v * 1000) / 1000) : `${Math.round(v * 10) / 10}px`);
  }
}

/** Mounted inside the header's `.hx-wrap`. Renders the solid strip that covers the
 *  tray above a pinned card, and (once per screen) the lab-bar switch. `toolbar` = a
 *  detail tab's own toolbar, which pins under the header in C only. */
export function StickyHeader({ wrap, toolbar = false }: { wrap: React.RefObject<HTMLDivElement | null>; toolbar?: boolean }) {
  const option = LOCKED;
  const first = useIsFirst(!toolbar);

  React.useEffect(() => {
    if (first) document.documentElement.dataset.sticky = option;
  }, [first, option]);

  React.useEffect(() => {
    const w = wrap.current;
    const tray = w?.closest<HTMLElement>(".pg-tray");
    if (!w || !tray) return;
    // C needs the scroll-linked timeline; without it C pins the whole card.
    const opt: StickyOption = option === "C" && !supportsScrollTimeline() ? "A" : option;
    const attr = toolbar ? "data-sx-tb" : "data-sx-root";
    let root: HTMLElement | null = null;
    let frame = 0;
    let faded = new Set<HTMLElement>();
    const unfade = (el: HTMLElement) => {
      el.removeAttribute("data-sx-fade");
      el.style.removeProperty("--sx-f0");
      el.style.removeProperty("--sx-f1");
    };

    // ── B "Condense": progress p = scrolled / reach, frame by frame ──
    let reach = 0; // how much the card shrinks, so how far the page scrolls while it does
    let folds: HTMLElement[] = [];
    let kept: HTMLElement[] = [];
    let scrollFrame = 0;
    const timeline = supportsScrollTimeline();
    const reduce = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
    const FOLD_VARS = ["--sx-fh", "--sx-fmt", "--sx-fmb"];
    const ROOT_VARS = ["--sx-h", "--sx-k", "--sx-below", "--sx-lip", "--sx-reach", "--sx-pt0", "--sx-pb0", "--sx-m0", "--sx-m1"];
    const unfold = (el: HTMLElement) => {
      el.removeAttribute("data-sx-fold");
      FOLD_VARS.forEach((k) => el.style.removeProperty(k));
    };
    const unkeep = (el: HTMLElement) => {
      el.removeAttribute("data-sx-keep");
      el.style.removeProperty("--sx-km");
    };
    const releaseB = (r: HTMLElement) => {
      folds.forEach(unfold);
      kept.forEach(unkeep);
      folds = [];
      kept = [];
      reach = 0;
      ["data-sx-c", "data-sx-rest", "data-sx-under", "data-sx-measuring", "data-sx-ready"].forEach((a) => r.removeAttribute(a));
      ROOT_VARS.forEach((k) => r.style.removeProperty(k));
      w.style.removeProperty("--sx-p");
    };
    /** Reads the open and condensed card in one synchronous pass: the open layout,
     *  every piece's own height and margins, then the layout at p = 1. Keeps the exact
     *  natural border-box height reserved, so the box and page below stay in place in
     *  every layout the pass asks for; returns the whole-pixel condensed reading. */
    const measureB = (r: HTMLElement) => {
      r.setAttribute("data-sx-measuring", "0");
      r.removeAttribute("data-sx-ready");
      folds.forEach(unfold);
      kept.forEach(unkeep);
      // The card opens under the reserve, and only then does the reserve come off. A
      // browser that sizes the box once more before it restyles the card inside (the
      // card sits in a size container) would otherwise meet the condensed card with no
      // reserve: a page one fold shorter for that layout. Settle the card itself before
      // reading the wrapper's natural height, not its previous rounded reserve.
      void w.offsetHeight;
      r.style.removeProperty("--sx-h");
      const head = w.querySelector<HTMLElement>(".hx-head");
      const list = foldPieces(w);
      const keepList = keptRows(w, list);
      for (const el of list) {
        const cs = getComputedStyle(el);
        el.style.setProperty("--sx-fh", `${el.offsetHeight}px`);
        el.style.setProperty("--sx-fmt", cs.marginTop);
        el.style.setProperty("--sx-fmb", cs.marginBottom);
        el.setAttribute("data-sx-fold", "");
      }
      for (const el of keepList) {
        el.style.setProperty("--sx-km", getComputedStyle(el).marginTop);
        el.setAttribute("data-sx-keep", el.matches(".hx-navrow") ? "nav" : "views");
      }
      if (head) {
        const hcs = getComputedStyle(head);
        r.style.setProperty("--sx-pt0", hcs.paddingTop);
        r.style.setProperty("--sx-pb0", hcs.paddingBottom);
      }
      const cover = w.querySelector<HTMLElement>(".hx-detail-cover");
      if (cover) {
        r.style.setProperty("--sx-m0", `${cover.offsetWidth}px`);
        r.style.setProperty("--sx-m1", `${w.clientWidth <= 480 ? 28 : 32}px`);
      }
      const title = w.querySelector<HTMLElement>(".hx-title");
      const fs = title ? parseFloat(getComputedStyle(title).fontSize) || 24 : 24;
      const k = Math.min(1, (w.clientWidth <= 480 ? 17 : 18) / fs);
      r.style.setProperty("--sx-k", String(Math.round(k * 1000) / 1000));
      const open = r.offsetHeight;
      // The exact open border-box height goes on reserve before the card condenses.
      // The condensed box can only be read with the reserve off, so for that layout its
      // bottom margin holds the exact room the card gives up, read at layout precision.
      const zone = w.querySelector<HTMLElement>(".hx-zone");
      const openBox = heightOf(r);
      const around = zone ? openBox - heightOf(zone) : 0;
      r.style.setProperty("--sx-h", `${openBox}px`);
      r.setAttribute("data-sx-ready", "");
      r.setAttribute("data-sx-measuring", "1");
      const room = zone ? heightOf(r) - heightOf(zone) - around : 0;
      const release = room > 0 ? holdRoom(r, room) : null;
      r.style.removeProperty("--sx-h");
      const shut = r.offsetHeight;
      r.style.setProperty("--sx-h", `${openBox}px`);
      release?.();
      // A detail page: the body card is joined under the header, so the strip under
      // the card is the body card's own top padding, in the card's paint.
      const body = r.nextElementSibling;
      const joined = body instanceof HTMLElement && body.matches(".hx-detail-body");
      r.style.setProperty("--sx-below", `${joined ? 0 : gapBelow(r)}px`);
      r.style.setProperty("--sx-lip", `${joined ? parseFloat(getComputedStyle(body).paddingTop) || 0 : 0}px`);
      reach = Math.max(0, open - shut);
      r.style.setProperty("--sx-reach", `${Math.max(1, reach)}px`);
      void r.offsetHeight;
      r.removeAttribute("data-sx-measuring");
      // Keep fractional precision during the loan, but rest on the same whole pixel
      // as the lab. Rounding the loan itself would move the page during that read.
      r.style.setProperty("--sx-h", `${open}px`);
      folds = list;
      kept = keepList;
      return shut;
    };
    /** Each scroll frame: the light state flags, and p itself where the browser has no
     *  scroll timeline (written in the same frame, so it never trails the page). */
    const evaluateB = () => {
      scrollFrame = 0;
      const r = root;
      if (!r || r.getAttribute("data-sx-root") !== "B") return;
      const scrollTop = tray.scrollTop;
      const top = Math.max(0, scrollTop);
      const done = reach >= 1 && top >= reach;
      r.toggleAttribute("data-sx-rest", scrollTop === 0);
      r.toggleAttribute("data-sx-under", top > 0.5);
      r.toggleAttribute("data-sx-c", done);
      if (!timeline) {
        const p = reach < 1 ? 0 : reduce?.matches ? (done ? 1 : 0) : Math.min(1, top / reach);
        w.style.setProperty("--sx-p", String(Math.round(p * 10000) / 10000));
      }
    };
    const onScroll = () => {
      if (!scrollFrame) scrollFrame = requestAnimationFrame(evaluateB);
    };

    const release = () => {
      faded.forEach(unfade);
      faded = new Set();
      if (!root) return;
      releaseB(root);
      root.removeAttribute(attr);
      ALL_VARS.forEach((k) => root?.style.removeProperty(k));
      if (toolbar) tray.style.removeProperty("--sx-tb-h");
      else {
        tray.style.removeProperty("--sx-hs");
        tray.style.removeProperty("--sx-lift");
        tray.removeAttribute("data-sx-on");
        tray.removeAttribute("data-sx-hs");
      }
      root = null;
    };

    const update = () => {
      frame = 0;
      if (!w.isConnected) return;
      // Only the page's own header sticks: the first one in the tray, sitting in a
      // box at least half the page's height (a gallery's sample headers never do).
      if (!toolbar && tray.querySelector(".hx-wrap:has(> .hx-zone)") !== w) return release();
      const { root: found, host } = findRoot(w, tray, toolbar);
      const tall = !!host && host.offsetHeight >= Math.min(tray.scrollHeight * 0.5, tray.clientHeight) - 1;
      const grid = !!host && getComputedStyle(host).display.includes("grid");
      // A toolbar pins only in C, only on a detail tab, under a pinned header.
      const toolbarOk = opt === "C" && !!w.closest(".hx-detail-body") && tray.getAttribute("data-sx-on") === "C";
      if (!host || !tall || grid || (toolbar && !toolbarOk)) return release();
      if (root && root !== found) release();
      root = found;
      root.setAttribute(attr, opt);
      if (toolbar) {
        const v = measureToolbar(root, host, w, tray);
        if (!v) return release();
        setVars(root, v);
        tray.style.setProperty("--sx-tb-h", `${Math.round(v["--sx-tb-pt"] + v["--sx-tb-bh"] + 12)}px`);
        return;
      }
      // A notice the page pins to the very top of the tray (offline) stays above the
      // header: the header pins under it.
      let lift = 0;
      for (const c of tray.children) {
        ro.observe(c); // a notice growing in, a page growing: measure again
        if (c.contains(w)) break;
        if (c instanceof HTMLElement && getComputedStyle(c).position === "sticky") lift += c.offsetHeight;
      }
      tray.style.setProperty("--sx-lift", `${lift}px`);
      if (opt === "B") {
        const shut = measureB(root);
        if (tray.getAttribute("data-sx-on") !== "B") tray.setAttribute("data-sx-on", "B");
        const hsB = String(Math.round(shut));
        tray.style.setProperty("--sx-hs", `${hsB}px`);
        if (tray.getAttribute("data-sx-hs") !== hsB) tray.setAttribute("data-sx-hs", hsB);
        evaluateB();
        return;
      }
      let used = opt;
      let m = measureHeader(root, w, opt);
      // A page too short to scroll the whole way would leave B or C stopped half way
      // (a row half faded): such a page keeps the whole card, like A.
      if (m && opt !== "A" && tray.scrollHeight - tray.clientHeight < (m.vars["--sx-d"] ?? 0)) {
        used = "A";
        root.setAttribute(attr, used);
        m = measureHeader(root, w, used);
      }
      if (!m) return release();
      setVars(root, m.vars);
      const now = new Set(m.fades.map(([el]) => el));
      faded.forEach((el) => {
        if (!now.has(el)) unfade(el);
      });
      for (const [el, a, b] of m.fades) {
        el.setAttribute("data-sx-fade", "");
        el.style.setProperty("--sx-f0", `${Math.round(a)}px`);
        el.style.setProperty("--sx-f1", `${Math.round(b)}px`);
      }
      faded = now;
      if (tray.getAttribute("data-sx-on") !== used) tray.setAttribute("data-sx-on", used);
      const hs = String(Math.round(m.stuck));
      tray.style.setProperty("--sx-hs", `${hs}px`);
      // The pinned height as an attribute too, so a toolbar below can follow it.
      if (tray.getAttribute("data-sx-hs") !== hs) tray.setAttribute("data-sx-hs", hs);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };

    const ro = new ResizeObserver(schedule);
    update();
    ro.observe(tray);
    // B's card changes height every scroll frame by design (its open height stays
    // reserved), so only A, C and toolbars watch the card itself.
    if (toolbar || opt !== "B") {
      ro.observe(w);
      const card = w.querySelector(".hx-head, .hx-toolbar");
      if (card) ro.observe(card);
    }
    // The page growing or shrinking (a list loads, a filter narrows it) changes how far
    // the tray can scroll.
    for (const page of tray.children) ro.observe(page);
    // Rows come and go (a notice, a status line, a tab count): re-measure.
    const mo = new MutationObserver(schedule);
    mo.observe(w, { childList: true, subtree: true });
    // A toolbar follows the header above it (it pins only under a C header).
    const trayMo = new MutationObserver(schedule);
    if (toolbar) trayMo.observe(tray, { attributes: true, attributeFilter: ["data-sx-on", "data-sx-hs"] });
    else trayMo.observe(tray, { childList: true });
    const fonts = typeof document !== "undefined" ? document.fonts : undefined;
    fonts?.addEventListener?.("loadingdone", schedule);
    if (!toolbar && opt === "B") {
      tray.addEventListener("scroll", onScroll, { passive: true });
      reduce?.addEventListener?.("change", onScroll);
    }
    return () => {
      cancelAnimationFrame(frame);
      cancelAnimationFrame(scrollFrame);
      tray.removeEventListener("scroll", onScroll);
      reduce?.removeEventListener?.("change", onScroll);
      ro.disconnect();
      mo.disconnect();
      trayMo.disconnect();
      fonts?.removeEventListener?.("loadingdone", schedule);
      release();
    };
  }, [wrap, option, toolbar]);

  return (
    <>
      <div className="sx-band" aria-hidden />
    </>
  );
}
