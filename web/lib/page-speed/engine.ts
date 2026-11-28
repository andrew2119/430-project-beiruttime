import type { PrefetchKind } from 'next/dist/client/components/router-reducer/router-reducer-types';
import { pageFor, warmPageAnswers } from './pages';
import type { ReadScope } from './scope';
import { IDLE_BATCH, IDLE_TIMEOUT_MS, IDLE_FALLBACK_MS, PAGE_REQUEST_HELD_MS, POINTER_REST_MS, VISIBLE_CHECK_MS } from './policy';
export type PageRouter = {prefetch:(href:string,options:{kind:PrefetchKind;onInvalidate:()=>void})=>void};
export function warmingAddress(element:Element,origin:string):string|null {
  const href = element.getAttribute('href');
  if (!href || !href.startsWith('/') || href.startsWith('//') || element.hasAttribute('download') || element.getAttribute('aria-disabled') === 'true' || ![null,'','_self'].includes(element.getAttribute('target'))) return null;
  try {const url = new URL(href,origin);return url.origin === origin && !url.hash && pageFor(url.pathname+url.search) ? url.pathname+url.search : null;} catch {return null;}
}
/** A request ledger, not a claim that Next finished downloading the full page.
 * Only production network evidence can establish readiness at the press. */
export function createPageWarmer(router:PageRouter,scope:ReadScope,clock:()=>number = Date.now,answers = warmPageAnswers) {
  const requested = new Map<string,{until:number}>();let live = true;
  return {warm(address:string,reads=true) {
    if (!live || !scope.valid() || !pageFor(address)) return;
    if ((requested.get(address)?.until ?? -Infinity) <= clock()) {
      // Bound the address ledger independently of caller-controlled query strings.
      if (requested.size >= 64) requested.delete(requested.keys().next().value!);
      const request = {until:clock()+PAGE_REQUEST_HELD_MS};requested.set(address,request);
      try {router.prefetch(address,{kind:'full' as PrefetchKind,onInvalidate:()=>{if (requested.get(address) === request) requested.delete(address);}});} catch {requested.delete(address);}
    }
    if (reads) void answers(address,scope).catch(()=>{});
  },stop() {live = false;requested.clear();}};
}
const idle = (run:()=>void)=>{
  if (typeof requestIdleCallback === 'function') {const id = requestIdleCallback(run,{timeout:IDLE_TIMEOUT_MS});return()=>cancelIdleCallback(id);}
  const id = setTimeout(run,IDLE_FALLBACK_MS);return()=>clearTimeout(id);
};
/** One adoption-only listener set, installed lazily after the real shell paints. */
export function startPageWarming(router:PageRouter,scope:ReadScope,doc:Document = document) {
  const warmer = createPageWarmer(router,scope), origin = doc.location.origin;
  let live = true, rest:ReturnType<typeof setTimeout>|undefined, resting:Element|null = null, cancelIdle:(()=>void)|null = null;
  const visible = new Set<Element>(), queued = new Map<Element,boolean>(), observed = new Set<Element>();
  const cancelRest = ()=>{clearTimeout(rest);rest = undefined;resting = null;};
  const destination = (target:EventTarget|null)=>target instanceof Element ? target.closest('a[href]') : null;
  const warm = (element:Element,reads=true)=>{const address = warmingAddress(element,origin);if (live && address && element.isConnected && address !== doc.location.pathname+doc.location.search) warmer.warm(address,reads);};
  const drain = ()=>{cancelIdle = null;if (!live || doc.hidden) {queued.clear();return;}for (const [element,reads] of [...queued].slice(0,IDLE_BATCH)) {queued.delete(element);if (visible.has(element)) warm(element,reads);}if (queued.size) cancelIdle = idle(drain);};
  const enqueue = (elements:Iterable<Element>,reads:boolean)=>{for (const element of elements) if (visible.has(element)) queued.set(element,(queued.get(element) ?? false) || reads);if (queued.size && !cancelIdle) cancelIdle = idle(drain);};
  const queue = (reads:boolean)=>enqueue(visible,reads);
  const seen = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver(entries=>{for (const entry of entries) {if (entry.isIntersecting) visible.add(entry.target);else {visible.delete(entry.target);queued.delete(entry.target);}}enqueue(entries.filter(entry=>entry.isIntersecting).map(entry=>entry.target),true);});
  const look = ()=>{
    for (const element of observed) if (!element.isConnected || !element.closest('[data-bt-glance]')) {seen?.unobserve(element);observed.delete(element);visible.delete(element);queued.delete(element);}
    doc.querySelectorAll('[data-bt-glance] a[href]').forEach(element=>{if (!observed.has(element) && warmingAddress(element,origin)) {observed.add(element);seen?.observe(element);}});
  };
  const changes = typeof MutationObserver === 'undefined' ? null : new MutationObserver(records=>{look();enqueue(records.filter(record=>record.type === 'attributes').map(record=>record.target as Element),true);});
  changes?.observe(doc.documentElement,{childList:true,subtree:true,attributes:true,attributeFilter:['href','data-bt-glance','aria-disabled','target','download']});look();
  const over = (event:PointerEvent)=>{if (event.pointerType !== 'mouse' || doc.hidden) return;const element = destination(event.target);if (!element || element === resting) return;cancelRest();resting = element;rest = setTimeout(()=>{resting = null;warm(element);},POINTER_REST_MS);};
  const out = (event:PointerEvent)=>{if (resting && !(event.relatedTarget instanceof Node && resting.contains(event.relatedTarget))) cancelRest();};
  const intent = (event:Event)=>{cancelRest();if (doc.hidden || ('button' in event && (event.button !== 0 || (event as MouseEvent).metaKey || (event as MouseEvent).ctrlKey || (event as MouseEvent).altKey || (event as MouseEvent).shiftKey))) return;const element = destination(event.target);if (element) warm(element);};
  const keep = ()=>{if (doc.hidden) {cancelRest();cancelIdle?.();cancelIdle = null;queued.clear();} else queue(false);};
  doc.addEventListener('pointerover',over);doc.addEventListener('pointerout',out);doc.addEventListener('pointerdown',intent);doc.addEventListener('focusin',intent);doc.addEventListener('visibilitychange',keep);
  // The engine may arrive after the person's focus/pointer already did.
  const focused = destination(doc.activeElement);if (focused && !doc.hidden) warm(focused);
  const hovered = destination([...doc.querySelectorAll(':hover')].at(-1) ?? null);if (hovered && hovered !== focused && !doc.hidden) warm(hovered);
  const timer = setInterval(keep,VISIBLE_CHECK_MS);
  return {ownsGlance:!!seen && !!changes,look(){look();queue(true);},stop(){live = false;cancelRest();cancelIdle?.();clearInterval(timer);changes?.disconnect();seen?.disconnect();warmer.stop();visible.clear();queued.clear();observed.clear();doc.removeEventListener('pointerover',over);doc.removeEventListener('pointerout',out);doc.removeEventListener('pointerdown',intent);doc.removeEventListener('focusin',intent);doc.removeEventListener('visibilitychange',keep);}};
}
