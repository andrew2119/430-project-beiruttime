import { prefersReducedMotion } from '../motion-tokens';
export type ToastKind = 'info'|'success'|'warning'|'error'|'loading';
export type ToastOptions = {id?:string; description?:string; durationMs?:number; action?:{label:string; run:()=>void|boolean}};
export type ToastRecord = {id:string; revision:number; title:string; description?:string; kind:ToastKind; action?:ToastOptions['action']; phase:'open'|'closed'};
type Entry = {view:ToastRecord; remaining:number; started:number; timer:ReturnType<typeof setTimeout>|undefined; paused:Set<string>; repeatable:boolean};
const entries = new Map<string,Entry>(), listeners = new Set<()=>void>();
const empty:readonly ToastRecord[] = [];
let snapshot:readonly ToastRecord[] = empty, serial = 0, revision = 0, mounted = 0, hidden = false;
const READ_LIFETIME_MS = 5000;
function publish() {snapshot = [...entries.values()].map(entry=>entry.view);for (const listener of listeners) listener();}
function clear(entry:Entry) {if (entry.timer !== undefined) clearTimeout(entry.timer);entry.timer = undefined;}
function arm(entry:Entry) {
  clear(entry);
  if (entry.view.phase !== 'open' || entry.paused.size || hidden || !Number.isFinite(entry.remaining)) return;
  entry.started = Date.now();entry.timer = setTimeout(()=>closeToast(entry.view.id,false,entry.view.revision),Math.max(0,entry.remaining));
}
export function subscribeToasts(listener:()=>void) {listeners.add(listener);return ()=>listeners.delete(listener);}
export const currentToasts = () => snapshot;
export const serverToasts = () => empty;
export function clearToasts() {for (const entry of entries.values()) clear(entry);entries.clear();publish();}
export function mountToastOutlet() {
  if (mounted) throw new Error('Mount the canonical notification outlet only once.');
  mounted++;let current = true;
  return ()=>{if (!current) return;current = false;mounted--;clearToasts();};
}
export function finishToast(id:string,revision:number) {const entry = entries.get(id);if (!entry || entry.view.revision !== revision) return;clear(entry);entries.delete(id);publish();}
export function closeToast(id:string,immediate = false,revision?:number) {
  const entry = entries.get(id);
  if (!entry || (revision !== undefined && entry.view.revision !== revision)) return;
  clear(entry);
  if (immediate || prefersReducedMotion() || !mounted) {entries.delete(id);publish();return;}
  entry.view = {...entry.view,phase:'closed'};publish();
}
export function pauseToast(id:string,reason:string,on:boolean) {
  const entry = entries.get(id);if (!entry || entry.view.phase !== 'open') return;
  if (on && !entry.paused.has(reason)) {if (!entry.paused.size && !hidden) entry.remaining -= Date.now()-entry.started;entry.paused.add(reason);clear(entry);}
  else if (!on && entry.paused.delete(reason)) arm(entry);
}
export function setToastVisibility(isHidden:boolean) {
  if (hidden === isHidden) return;
  for (const entry of entries.values()) {if (isHidden && !entry.paused.size) entry.remaining -= Date.now()-entry.started;clear(entry);}
  hidden = isHidden;
  if (!hidden) for (const entry of entries.values()) arm(entry);
}
function show(kind:ToastKind,title:string,options:ToastOptions = {}):string {
  const duration = kind === 'loading' ? Infinity : options.durationMs ?? READ_LIFETIME_MS;
  if (duration !== Infinity && (!Number.isFinite(duration) || duration < 0)) throw new RangeError('Notification lifetime must be nonnegative or Infinity.');
  const repeatable = options.id === undefined && !options.action;
  const repeated = repeatable ? [...entries.values()].find(entry=>entry.repeatable && entry.view.phase === 'open' && entry.view.kind === kind && entry.view.title === title && entry.view.description === options.description) : undefined;
  const id = options.id ?? repeated?.view.id ?? `bt-notice-${++serial}`, previous = entries.get(id);
  if (previous) clear(previous);
  const view:ToastRecord = {id,revision:++revision,title,description:options.description,kind,action:options.action ? {label:options.action.label,run:options.action.run} : undefined,phase:'open'};
  const entry:Entry = {view,remaining:duration,started:Date.now(),timer:undefined,paused:previous?.view.phase === 'open' ? previous.paused : new Set(),repeatable};
  entries.set(id,entry);arm(entry);publish();return id;
}
export const toast = Object.assign((title:string,options?:ToastOptions)=>show('info',title,options),{
  success:(title:string,options?:ToastOptions)=>show('success',title,options),
  warning:(title:string,options?:ToastOptions)=>show('warning',title,options),
  error:(title:string,options?:ToastOptions)=>show('error',title,options),
  loading:(title:string,options?:ToastOptions)=>show('loading',title,options),
  info:(title:string,options?:ToastOptions)=>show('info',title,options),
  dismiss:(id?:string)=>{for (const key of id ? [id] : [...entries.keys()]) closeToast(key);},
});
