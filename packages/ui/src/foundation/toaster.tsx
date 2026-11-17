'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useSyncExternalStore, type RefObject } from 'react';
import * as PortalPrimitive from '@radix-ui/react-dialog';
import { Check, CircleAlert, Clock3, Info, TriangleAlert, X } from 'lucide-react';
import { Button } from './button';
import { useDirection } from './direction';
import { retainExit } from './presence';
import { useDragSurface } from './use-drag-surface';
import { useSurfaceEntrance } from './entrance';
import { markMotionInput } from '../motion-tokens';
import { ToastAccess } from './toast-access';
import { reserveToastSpace } from './toast-room';
import { clearToasts, closeToast, currentToasts, finishToast, mountToastOutlet, pauseToast, serverToasts, setToastVisibility, subscribeToasts, type ToastRecord } from './toast-store';
export { toast } from './toast-store';

function ToastCard({entry,dismissLabel}: {entry:ToastRecord; dismissLabel:string}) {
  const panelRef = useRef<HTMLDivElement|null>(null), shadeRef = useRef<HTMLElement|null>(null);
  const drag = useDragSurface(panelRef,shadeRef,()=>closeToast(entry.id,true,entry.revision),()=>true,()=>panelRef.current?.closest<HTMLElement>('[data-bt-toast-region]') ?? null);
  const entrance = useSurfaceEntrance(shadeRef,entry.phase === 'open','none');
  const attach = useCallback((node:HTMLDivElement|null)=>{const stopDrag = drag(node), stopEntry = entrance(node);return ()=>{stopEntry?.();stopDrag?.();};},[drag,entrance]);
  useLayoutEffect(()=>{
    if (entry.phase !== 'closed' || !panelRef.current) return;
    return retainExit(panelRef.current,()=>finishToast(entry.id,entry.revision));
  },[entry.id,entry.revision,entry.phase]);
  const Icon = entry.kind === 'success' ? Check : entry.kind === 'error' ? CircleAlert : entry.kind === 'warning' ? TriangleAlert : entry.kind === 'loading' ? Clock3 : Info;
  return <div ref={attach} className="bt-toast-card bt-sheet-bottom" data-bt-toast="" data-kind={entry.kind} data-state={entry.phase} data-dismiss-side="down" aria-atomic="true" inert={entry.phase === 'closed' ? true : undefined} aria-hidden={entry.phase === 'closed' ? true : undefined}
    onPointerEnter={()=>pauseToast(entry.id,'hover',true)} onPointerLeave={()=>pauseToast(entry.id,'hover',false)}
    onFocusCapture={()=>pauseToast(entry.id,'focus',true)} onBlurCapture={event=>{if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) pauseToast(entry.id,'focus',false);}}>
    <span className="bt-toast-icon" aria-hidden="true"><Icon/></span>
    <div className="bt-toast-copy"><p className="bt-toast-title">{entry.title}</p>{entry.description && <p className="bt-toast-description">{entry.description}</p>}
      {entry.action && <Button variant="outline" size="sm" onClick={event=>{if (entry.action?.run() !== false) closeToast(entry.id,event.detail === 0,entry.revision);}}>{entry.action.label}</Button>}
    </div>
    <Button variant="ghost" size="icon" aria-label={dismissLabel} onClick={event=>closeToast(entry.id,event.detail === 0,entry.revision)}><X aria-hidden="true"/></Button>
  </div>;
}

/** One canonical queue/outlet. The frozen root outlet receives only its own
 * legacy calls until the shell moves; the two queues never duplicate a toast. */
export function Toaster({label,dismissLabel,contentRef}: {label:string; dismissLabel:string; contentRef:RefObject<HTMLElement|null>}) {
  const entries = useSyncExternalStore(subscribeToasts,currentToasts,serverToasts);
  const direction = useDirection();
  const regionRef = useRef<HTMLDivElement|null>(null);
  const attach = useCallback((node:HTMLDivElement|null)=>{
    regionRef.current = node;if (!node) return;
    const release = mountToastOutlet(), room = reserveToastSpace(node,()=>contentRef.current);
    const measure = ()=>{node.toggleAttribute('data-overflow',node.scrollHeight > node.clientHeight + 1);room.measure();};
    measure();let observer:ResizeObserver|undefined;
    if (typeof ResizeObserver !== 'undefined') {observer = new ResizeObserver(measure);observer.observe(node);if (node.firstElementChild) observer.observe(node.firstElementChild);}
    return ()=>{observer?.disconnect();room.restore();if (regionRef.current === node) regionRef.current = null;release();};
  },[contentRef]);
  useEffect(()=>{
    const visibility = ()=>setToastVisibility(document.hidden);
    const keyboard = ()=>{if (regionRef.current) markMotionInput(regionRef.current,'keyboard');};
    const pointer = ()=>{if (regionRef.current) markMotionInput(regionRef.current,'pointer');};
    document.addEventListener('visibilitychange',visibility);window.addEventListener('bt:access-change',clearToasts);window.addEventListener('keydown',keyboard,true);window.addEventListener('pointerdown',pointer,true);visibility();
    return ()=>{document.removeEventListener('visibilitychange',visibility);window.removeEventListener('bt:access-change',clearToasts);window.removeEventListener('keydown',keyboard,true);window.removeEventListener('pointerdown',pointer,true);};
  },[]);
  return <PortalPrimitive.Root open modal={false}><PortalPrimitive.Portal forceMount><div ref={attach} className="bt-toast-outlet" data-bt-toast-region="" data-active={entries.length ? '' : undefined} role="region" aria-label={label} aria-live="polite" aria-relevant="additions text" tabIndex={-1} dir={direction.dir} lang={direction.lang}>
    <ol className="bt-toast-list">{entries.map(entry=><li key={entry.id}><ToastCard entry={entry} dismissLabel={dismissLabel}/></li>)}</ol>
  </div><ToastAccess regionRef={regionRef} label={label}/></PortalPrimitive.Portal></PortalPrimitive.Root>;
}
