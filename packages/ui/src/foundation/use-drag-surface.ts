'use client';

import { useCallback, useLayoutEffect, useRef, type RefObject } from 'react';
import type { DragParts } from './drag-engine';
import { attachTouchDismiss, touchCapable } from './drag-loader';

/** The mouse-only path never imports the touch engine; failures keep the
 * ordinary close/keyboard/outside behavior and a later open may retry. */
export function useDragSurface(panelRef:RefObject<HTMLElement|null>, shadeRef:RefObject<HTMLElement|null>, dismiss:()=>void, allowed:(event:TouchEvent)=>boolean, scrollBoundary?:()=>HTMLElement|null) {
  const callbacks = useRef({dismiss,allowed,scrollBoundary});
  useLayoutEffect(() => {callbacks.current = {dismiss,allowed,scrollBoundary};}, [dismiss,allowed,scrollBoundary]);
  return useCallback((node:HTMLDivElement|null) => {
    panelRef.current = node;
    if (!node) return;
    const parts:DragParts = {shade:()=>shadeRef.current, dismiss:()=>callbacks.current.dismiss(), allowed:event=>callbacks.current.allowed(event), scrollBoundary:()=>callbacks.current.scrollBoundary?.() ?? null};
    const detach = attachTouchDismiss(node,parts,touchCapable());
    return () => {detach();if (panelRef.current === node) panelRef.current = null;};
  }, [panelRef,shadeRef]);
}
