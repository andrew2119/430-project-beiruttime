'use client';

import { useCallback, useLayoutEffect, useRef, type RefObject } from 'react';
import { prefersReducedMotion } from '../motion-tokens';
const owners = new WeakMap<HTMLElement,symbol>();
/** One staged first frame for engines without the native starting-style rule. */
export function stageSurfaceEntry(parts:readonly HTMLElement[],input:()=>string|undefined) {
  const immediate = ()=>['keyboard','off'].includes(input() ?? '') || prefersReducedMotion();
  if (!parts.length || typeof window === 'undefined' || 'CSSStartingStyleRule' in window || immediate() || parts.some(part=>part.dataset.state !== 'open')) return ()=>{};
  const owner = Symbol(), frames = new Set<number>();let active = true;
  const cancel = ()=>{
    if (!active) return;active = false;for (const frame of frames) window.cancelAnimationFrame(frame);frames.clear();
    for (const part of parts) if (owners.get(part) === owner) {part.removeAttribute('data-starting');owners.delete(part);}
  };
  const eligible = ()=>active && !immediate() && parts.every(part=>part.isConnected && part.dataset.state === 'open' && owners.get(part) === owner);
  for (const part of parts) {owners.set(part,owner);part.setAttribute('data-starting','');}
  void parts[0].offsetWidth;
  const frame = (run:()=>void)=>{const id = window.requestAnimationFrame(()=>{frames.delete(id);if (eligible()) run();else cancel();});frames.add(id);};
  frame(()=>frame(cancel));return cancel;
}
/** Stable attachment avoids replacing the drag/focus ref on a state change. */
export function useSurfaceEntrance(shadeRef:RefObject<HTMLElement|null>,open:boolean,input:string) {
  const cancelRef = useRef<(()=>void)|undefined>(undefined);
  useLayoutEffect(()=>{if (!open || input === 'keyboard' || prefersReducedMotion()) cancelRef.current?.();},[open,input]);
  useLayoutEffect(()=>()=>cancelRef.current?.(),[]);
  return useCallback((node:HTMLElement|null)=>{
    if (!node) return;
    cancelRef.current?.();
    const shade = shadeRef.current, parts = shade ? [node,shade] : [node];
    const cancel = stageSurfaceEntry(parts,()=>node.closest('[data-bt-motion="off"]') ? 'off' : node.closest<HTMLElement>('[data-bt-motion-input]')?.dataset.btMotionInput);
    cancelRef.current = cancel;
    return ()=>{cancel();if (cancelRef.current === cancel) cancelRef.current = undefined;};
  },[shadeRef]);
}
