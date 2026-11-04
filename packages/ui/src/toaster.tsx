"use client";

import * as React from "react";
import { Toaster as Sonner } from "sonner";
export { toast } from "sonner";

/**
 * Global toast outlet (sonner — RATIFIED OD-17c). Queues natively, which is
 * the deliberate small UX upgrade over the monolith's single-slot Toast
 * (04a1 §9). classic/light are light surfaces; only dark maps to dark.
 */
export function Toaster({ theme, dir = "ltr" }: { theme: "light" | "dark"; dir?: "ltr" | "rtl" }) {
  React.useEffect(() => {
    const phone = window.matchMedia("(max-width: 600px)");
    const resize = new ResizeObserver(() => measure());
    let observed: HTMLElement | null = null;

    // The room covers the whole resting stack: toasts queued behind the front one peek
    // above it, so it runs from the front toast's foot to the highest toast's top.
    const measure = () => {
      const tray = document.querySelector<HTMLElement>("main.pg-tray");
      const resting = phone.matches
        ? [...document.querySelectorAll<HTMLElement>('[data-sonner-toaster] [data-sonner-toast][data-mounted="true"]:not([data-removed="true"]):not([data-visible="false"])')]
        : [];
      const front = resting.find((toast) => toast.dataset.front === "true") ?? null;
      if (front !== observed) {
        resize.disconnect();
        observed = front;
        if (front) resize.observe(front);
      }
      if (!tray) return;
      // A reader already at the page's end stays there as the room grows, so a toast that
      // arrives then does not come to rest over the end of the page.
      const atFoot = tray.scrollTop >= tray.scrollHeight - tray.clientHeight - 1;
      const height = tray.scrollHeight;
      if (front) {
        const top = Math.min(...resting.map((toast) => toast.getBoundingClientRect().top));
        tray.style.setProperty("--toast-room", `${Math.ceil(front.getBoundingClientRect().bottom - top)}px`);
      } else tray.style.removeProperty("--toast-room");
      if (atFoot && tray.scrollHeight > height) tray.scrollTop = tray.scrollHeight;
    };
    // A toast's place is set by its transition, so the stack is measured again once one ends.
    const settled = (event: TransitionEvent) => {
      if (event.target instanceof Element && event.target.matches("[data-sonner-toast]")) measure();
    };

    const mutations = new MutationObserver(measure);
    mutations.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-front", "data-mounted", "data-removed", "data-visible", "data-expanded"] });
    phone.addEventListener("change", measure);
    document.addEventListener("transitionend", settled);
    measure();
    return () => {
      mutations.disconnect();
      resize.disconnect();
      phone.removeEventListener("change", measure);
      document.removeEventListener("transitionend", settled);
      document.querySelector<HTMLElement>("main.pg-tray")?.style.removeProperty("--toast-room");
    };
  }, []);
  return (
    <Sonner
      theme={theme === "dark" ? "dark" : "light"}
      position="bottom-center"
      dir={dir}
      richColors
    />
  );
}
