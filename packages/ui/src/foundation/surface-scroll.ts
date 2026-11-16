'use client';

import { useLayoutEffect } from 'react';
let owners = 0;
let release:undefined|(()=>void);
/** Scroll ownership follows logical openness, never a decorative exit hold. */
export function lockSurfaceScroll() {
  if (owners++ === 0) {
    const body = document.body, overflow = body.style.overflow, padding = body.style.paddingInlineEnd;
    const gap = Math.max(0,window.innerWidth-document.documentElement.clientWidth);
    const existing = Number.parseFloat(getComputedStyle(body).paddingInlineEnd) || 0;
    body.style.overflow = 'hidden';
    if (gap) body.style.paddingInlineEnd = `${existing+gap}px`;
    release = () => {body.style.overflow = overflow;body.style.paddingInlineEnd = padding;};
  }
  let active = true;
  return () => {if (!active) return;active = false;if (--owners === 0) {release?.();release = undefined;}};
}
export function useSurfaceScroll(open:boolean) {useLayoutEffect(()=>open ? lockSurfaceScroll() : undefined,[open]);}
