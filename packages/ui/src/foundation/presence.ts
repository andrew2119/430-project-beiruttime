'use client';

import { useLayoutEffect, useState, type RefObject } from 'react';
import { prefersReducedMotion, readMotionToken } from '../motion-tokens';

/** A transition hold has one cancellation owner. Child events cannot finish it. */
export function retainExit(node:HTMLElement, finish:()=>void): ()=>void {
  let current = true;
  const complete = () => {if (!current) return; current = false; window.clearTimeout(timer); node.removeEventListener('transitionend', ended); finish();};
  const ended = (event:TransitionEvent) => {if (event.target === node && ['opacity','transform'].includes(event.propertyName) && Number.parseFloat(getComputedStyle(node).opacity) <= 0.001) complete();};
  const duration = readMotionToken('--bt-motion-exit', node) ?? 0;
  // Normal completion is the event; two periods bound a missing-event hold.
  const timer = window.setTimeout(complete, duration * 2);
  node.addEventListener('transitionend', ended);
  return () => {current = false; window.clearTimeout(timer); node.removeEventListener('transitionend', ended);};
}

export function useSurfacePresence(open:boolean, input:'pointer'|'keyboard'|'none', node:RefObject<HTMLElement|null>, skipExit = false): boolean {
  const [snapshot, setSnapshot] = useState({open, held:open});
  if (snapshot.open !== open) setSnapshot({open, held:open || snapshot.held});
  const immediate = skipExit || input === 'keyboard' || prefersReducedMotion();
  const present = open || (snapshot.held && !immediate);
  useLayoutEffect(() => {
    if (open || !present || !node.current) return;
    return retainExit(node.current, () => setSnapshot(current => current.open ? current : {...current, held:false}));
  }, [open, present, node]);
  return present;
}
