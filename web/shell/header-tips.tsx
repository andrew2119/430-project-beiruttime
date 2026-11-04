"use client";
import * as React from "react";
import { createPortal } from "react-dom";
type Tip = { label: string; x: number; y: number; below: boolean };
const TIP_SELECTOR = "[data-hx-tip], .hx-ownfilter > button";
/** A button does not show its whole name: its icon alone (its words hidden at this
 *  size), a short phone label, or words cut short (a squeezed primary label). */
function iconOnly(el: HTMLElement) {
  if (el.innerText.trim() === "" || parseFloat(getComputedStyle(el).fontSize) === 0) return true;
  if (el.querySelector<HTMLElement>(".hx-act-label-phone")?.offsetParent) return true;
  return [...el.querySelectorAll<HTMLElement>(".hx-act-label")].some((l) => l.offsetParent !== null && l.scrollWidth > l.clientWidth + 1);
}
function tipLabel(el: HTMLElement) {
  return el.dataset.hxTip || el.getAttribute("aria-label") || el.textContent?.trim() || "";
}

/** Names the header's icon-only buttons: a long press on a touch screen (the
 *  following click is swallowed, so a long press never acts), hover with a mouse,
 *  or keyboard focus. One bubble per header, in the site's popover look. */
export function useHeaderTips(root: React.RefObject<HTMLElement | null>) {
  const [tip, setTip] = React.useState<Tip | null>(null);
  React.useEffect(() => {
    const el = root.current;
    if (!el) return;
    let timer: number | undefined;
    let linger: number | undefined;
    let pressed: HTMLElement | null = null;
    let named: HTMLElement | null = null;
    const find = (t: EventTarget | null) => {
      const hit = t instanceof Element ? t.closest<HTMLElement>(TIP_SELECTOR) : null;
      return hit && el.contains(hit) ? hit : null;
    };
    const show = (b: HTMLElement) => {
      if (!b.isConnected || !iconOnly(b) || b.getAttribute("aria-expanded") === "true") return;
      const r = b.getBoundingClientRect();
      const below = r.top < 56;
      named = b;
      setTip({ label: tipLabel(b), x: r.left + r.width / 2, y: below ? r.bottom : r.top, below });
    };
    const wait = () => {
      window.clearTimeout(timer);
      timer = undefined;
    };
    const hide = () => {
      wait();
      window.clearTimeout(linger);
      named = null;
      setTip(null);
    };
    const down = (e: PointerEvent) => {
      const b = find(e.target);
      if (!b || e.pointerType === "mouse") return;
      hide();
      pressed = null;
      timer = window.setTimeout(() => {
        timer = undefined;
        show(b);
        if (named === b) pressed = b;
      }, 450);
    };
    const up = (e: PointerEvent) => {
      if (e.pointerType === "mouse") return;
      wait();
      if (named) linger = window.setTimeout(hide, 1100);
    };
    const click = (e: MouseEvent) => {
      if (!pressed) return;
      const b = find(e.target);
      if (b && b === pressed) {
        e.preventDefault();
        e.stopPropagation();
      }
      pressed = null;
    };
    const menu = (e: Event) => {
      if (find(e.target) && (pressed || timer)) e.preventDefault();
    };
    const over = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      const b = find(e.target);
      if (!b || b === named) return;
      hide();
      timer = window.setTimeout(() => {
        timer = undefined;
        show(b);
      }, 350);
    };
    const out = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      const b = find(e.target);
      if (b && !(e.relatedTarget instanceof Node && b.contains(e.relatedTarget))) hide();
    };
    const focus = (e: FocusEvent) => {
      const b = find(e.target);
      if (b && b.matches(":focus-visible")) show(b);
    };
    el.addEventListener("pointerdown", down);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    el.addEventListener("click", click, true);
    el.addEventListener("contextmenu", menu);
    el.addEventListener("pointerover", over);
    el.addEventListener("pointerout", out);
    el.addEventListener("focusin", focus);
    el.addEventListener("focusout", hide);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => {
      hide();
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      el.removeEventListener("click", click, true);
      el.removeEventListener("contextmenu", menu);
      el.removeEventListener("pointerover", over);
      el.removeEventListener("pointerout", out);
      el.removeEventListener("focusin", focus);
      el.removeEventListener("focusout", hide);
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
    };
  }, [root]);
  return tip;
}

/** The bubble: centred on its button, kept 8 px inside the screen. */
export function TipBubble({ tip }: { tip: Tip | null }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [shift, setShift] = React.useState(0);
  React.useLayoutEffect(() => {
    const b = ref.current;
    if (!b || !tip) return;
    const w = b.offsetWidth;
    const left = tip.x - w / 2;
    const max = document.documentElement.clientWidth - 8 - w;
    setShift(left < 8 ? 8 - left : left > max ? max - left : 0);
  }, [tip]);
  if (!tip || typeof document === "undefined") return null;
  return createPortal(
    <div
      ref={ref}
      role="tooltip"
      className="hx-tip"
      data-below={tip.below || undefined}
      style={{ left: tip.x + shift, insetBlockStart: tip.y }}
    >
      {tip.label}
    </div>,
    document.body,
  );
}


export function useTitleFit(row: React.RefObject<HTMLDivElement | null>) {
  const [fit, setFit] = React.useState<"" | "tight" | "squeeze">("");
  const check = React.useCallback(() => {
    const el = row.current;
    const wrap = el?.closest<HTMLElement>(".hx-wrap");
    if (!el || !wrap || wrap.clientWidth === 0) return; // not on screen: keep the last answer
    if (wrap.clientWidth > 480 || el.hasAttribute("data-media")) return setFit("");
    const title = el.querySelector<HTMLElement>(".hx-title");
    const actions = el.querySelector<HTMLElement>(".hx-actions");
    if (!title || !actions) return setFit("");
    const em = title.scrollWidth / (parseFloat(getComputedStyle(title).fontSize) || 20);
    const kids = [...actions.children].filter((k) => getComputedStyle(k).display !== "none") as HTMLElement[];
    let need = Math.max(0, kids.length - 1) * (parseFloat(getComputedStyle(actions).columnGap) || 0);
    for (const k of kids) {
      const cs = getComputedStyle(k);
      need += k.getBoundingClientRect().width + (parseFloat(cs.marginLeft) || 0) + (parseFloat(cs.marginRight) || 0);
      k.querySelectorAll<HTMLElement>(".hx-act-label").forEach((l) => {
        if (l.offsetParent !== null) need += l.scrollWidth - l.clientWidth;
      });
    }
    const room = el.clientWidth;
    setFit(em * 20 + 12 + need <= room ? "" : em * 18 + 8 + need <= room ? "tight" : "squeeze");
  }, [row]);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- measures the title row after layout, then picks how the title fits (the lab's own measure-then-draw step)
  React.useLayoutEffect(check);
  React.useEffect(() => {
    const el = row.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(check);
    ro.observe(el);
    const actions = el.querySelector(".hx-actions");
    if (actions) ro.observe(actions);
    // A font switch changes every width without resizing the row.
    const fonts = typeof document !== "undefined" ? document.fonts : undefined;
    fonts?.addEventListener?.("loadingdone", check);
    const mo = new MutationObserver(check);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-font"] });
    return () => {
      ro.disconnect();
      mo.disconnect();
      fonts?.removeEventListener?.("loadingdone", check);
    };
  }, [row, check]);
  return fit;
}

