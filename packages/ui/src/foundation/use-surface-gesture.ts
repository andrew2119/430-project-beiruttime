'use client';

import { useCallback, type RefObject } from 'react';
import type { DialogContentProps } from '@radix-ui/react-dialog';
import { useSurface } from './surface-context';
import { useDragSurface } from './use-drag-surface';
import { useSurfaceEntrance } from './entrance';
export type DismissGuards = Pick<DialogContentProps,'onPointerDownOutside'|'onInteractOutside'>;

/** Gesture dismissal obeys the same cancellable guards as an outside press. */
export function useSurfaceGesture(panelRef:RefObject<HTMLElement|null>, shadeRef:RefObject<HTMLElement|null>, guards:DismissGuards) {
  const state = useSurface();
  const entrance = useSurfaceEntrance(shadeRef,state.open,state.input);
  const drag = useDragSurface(panelRef,shadeRef,state.dismissInstant,event=>{
    const outside = new CustomEvent('bt-surface-dismiss',{cancelable:true,detail:{originalEvent:event}});
    panelRef.current?.dispatchEvent(outside);
    guards.onPointerDownOutside?.(outside as unknown as Parameters<NonNullable<DialogContentProps['onPointerDownOutside']>>[0]);
    guards.onInteractOutside?.(outside as unknown as Parameters<NonNullable<DialogContentProps['onInteractOutside']>>[0]);
    return !outside.defaultPrevented;
  });
  return useCallback((node:HTMLDivElement|null)=>{
    const stopDrag = drag(node), stopEntry = entrance(node);
    return ()=>{stopEntry?.();stopDrag?.();};
  },[drag,entrance]);
}
