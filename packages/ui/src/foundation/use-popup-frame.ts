'use client';

import { useCallback, useRef, useState } from 'react';
import { useSurface } from './surface-context';
import { useSurfacePresence } from './presence';
import { useSurfaceGesture, type DismissGuards } from './use-surface-gesture';
import { useSurfaceFocus } from './surface-focus';

/** Geometry is measured once on attachment, not copied into a script scale. */
export function usePopupFrame(guards:DismissGuards, onOpen?:((event:Event)=>void), onClose?:((event:Event)=>void)) {
  const state = useSurface(), panelRef = useRef<HTMLDivElement|null>(null), shadeRef = useRef<HTMLDivElement|null>(null);
  const present = useSurfacePresence(state.open,state.input,panelRef,state.skipExit);
  const drag = useSurfaceGesture(panelRef,shadeRef,guards);
  const focus = useSurfaceFocus(panelRef,onOpen,onClose), {remember} = focus;
  const [gap,setGap] = useState(0);
  const attach = useCallback((node:HTMLDivElement|null) => {
    const cleanup = drag(node);
    let observer:ResizeObserver|undefined;
    if (node) {
      remember();
      const raw = getComputedStyle(node).getPropertyValue('--bt-space-2').trim();
      const measured = /^\d+(?:\.\d+)?px$/.test(raw) ? Number.parseFloat(raw) : 0;
      setGap(current => current === measured ? current : measured);
      const overflow = () => node.toggleAttribute('data-overflow',node.scrollHeight > node.clientHeight + 1);
      overflow();
      if (typeof ResizeObserver !== 'undefined') {observer = new ResizeObserver(overflow); observer.observe(node); for (const child of node.children) observer.observe(child);}
    }
    return () => {observer?.disconnect(); cleanup?.();};
  }, [drag,remember]);
  return {state,present,attach,gap,focus};
}
