'use client';

import { useCallback, useRef, type FocusEvent, type RefObject } from 'react';
export function shouldRestoreSurfaceFocus(active:Element|null,panel:HTMLElement|null) {return !active || active === document.body || Boolean(panel?.contains(active));}
/** Triggerless controlled surfaces restore the invoking control too. */
export function useSurfaceFocus(panelRef:RefObject<HTMLElement|null>,onOpen?:((event:Event)=>void), onClose?:((event:Event)=>void)) {
  const returnFocus = useRef<HTMLElement|null>(null), lastPanel = useRef<HTMLElement|null>(null);
  const remember = useCallback(() => {returnFocus.current = document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : null;lastPanel.current = panelRef.current;}, [panelRef]);
  const capture = useCallback((event:Event) => {remember();onOpen?.(event);}, [remember,onOpen]);
  const restore = useCallback((event:Event) => {
    onClose?.(event);
    if (event.defaultPrevented) return;
    // Closing paint must not steal a newer click or a nonmodal Tab destination.
    event.preventDefault();
    if (shouldRestoreSurfaceFocus(document.activeElement,panelRef.current ?? lastPanel.current) && returnFocus.current?.isConnected) returnFocus.current.focus({preventScroll:true});
  }, [onClose,panelRef]);
  const reveal = useCallback((event:FocusEvent<HTMLElement>) => {
    if (event.target instanceof HTMLElement) event.target.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
  }, []);
  return {remember,capture,restore,reveal};
}
