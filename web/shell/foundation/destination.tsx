'use client';

import Link, { useLinkStatus } from 'next/link';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { readMotionToken, markMotionInput } from '@beirut-time/ui/motion';
import { NavigationIcon, type NavigationDestination } from '@/shell/navigation-icon';
import { usePageWarmingRunning } from '@/lib/page-speed/running';
import { delayedPending } from '@/lib/page-speed/delay';
import { pageFor } from '@/lib/page-speed/pages';
const indications = new WeakMap<HTMLAnchorElement,symbol>();
function DelayedIcon({id,active,owner}: {id:NavigationDestination;active:boolean;owner:RefObject<HTMLAnchorElement|null>}) {
  const [shown,setShown] = useState(false);
  useEffect(()=>{const delay = readMotionToken('--bt-motion-pending');if (delay == null) return;const anchor = owner.current, previous = anchor?.getAttribute('aria-busy'), token = Symbol();
    const stop = delayedPending(delay,()=>{if (anchor && (!anchor.isConnected || owner.current !== anchor)) return;setShown(true);if (anchor) {indications.set(anchor,token);anchor.setAttribute('aria-busy','true');}});
    return ()=>{stop();if (anchor && indications.get(anchor) === token) {if (previous == null) anchor.removeAttribute('aria-busy');else anchor.setAttribute('aria-busy',previous);indications.delete(anchor);}};
  },[owner]);
  return <NavigationIcon id={id} active={active} pending={shown}/>;
}
function DestinationIcon({id,active,path,owner}: {id:NavigationDestination;active:boolean;path:string;owner:RefObject<HTMLAnchorElement|null>}) {
  const {pending} = useLinkStatus();
  return pending ? <DelayedIcon key={path} id={id} active={active} owner={owner}/> : <NavigationIcon id={id} active={active}/>;
}
/** Full-route prefetch remains until the lazy warmer has installed listeners.
 * Registered destinations share route intent. Native links keep new-tab and
 * modified-click behavior; pending feedback never replaces or moves the label. */
export function DestinationLink({href,label,icon,active=false,disabled=false,path,appearance='row'}: {href:string;label:string;icon:NavigationDestination;active?:boolean;disabled?:boolean;path:string;appearance?:'row'|'tab'}) {
  const running = usePageWarmingRunning(), owner = useRef<HTMLAnchorElement|null>(null);
  return <Link ref={owner} href={href} prefetch={disabled ? false : pageFor(href) && running ? false : true} aria-current={active ? 'page' : undefined} aria-disabled={disabled || undefined} tabIndex={disabled ? -1 : undefined}
    className={appearance === 'tab' ? 'bt-destination bt-destination-tab bt-pressable' : 'bt-destination bt-pressable'}
    onClick={event=>{if (disabled) event.preventDefault();}} onPointerDown={event=>markMotionInput(event.currentTarget,'pointer')} onKeyDown={event=>{markMotionInput(event.currentTarget,'keyboard');if (disabled && ['Enter',' '].includes(event.key)) event.preventDefault();}} onFocus={event=>{if (event.currentTarget.matches(':focus-visible')) markMotionInput(event.currentTarget,'keyboard');}}>
    <DestinationIcon id={icon} active={active} path={path} owner={owner}/><span className="bt-destination-label">{label}</span>
  </Link>;
}
