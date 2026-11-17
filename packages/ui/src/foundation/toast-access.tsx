'use client';

import { useEffect, useRef, useState, type RefObject } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { attachToastReach } from './toast-reach';
const stay = (event:Event) => event.preventDefault();

/** A temporary nonmodal focus scope pauses the modal scope underneath. It uses
 * the public modal primitive, without importing a private focus implementation. */
export function ToastAccess({regionRef,label}: {regionRef:RefObject<HTMLElement|null>;label:string}) {
  const [reaching,setReaching] = useState(false), reachRef = useRef<ReturnType<typeof attachToastReach>|undefined>(undefined);
  useEffect(()=>{
    const reach = attachToastReach(()=>regionRef.current,setReaching);reachRef.current = reach;
    return ()=>{reach.dispose();if (reachRef.current === reach) reachRef.current = undefined;};
  },[regionRef]);
  // Child focus scopes register before this effect. Alt+T never sends focus
  // into a still-active underlying trap while the bridge is being installed.
  useEffect(()=>{if (reaching) reachRef.current?.commit();},[reaching]);
  if (!reaching) return null;
  return <Dialog.Root open modal={false}><Dialog.Content forceMount hidden aria-describedby={undefined} onOpenAutoFocus={stay} onCloseAutoFocus={stay} onInteractOutside={stay} onEscapeKeyDown={stay}><Dialog.Title>{label}</Dialog.Title></Dialog.Content></Dialog.Root>;
}
