import type { DragParts } from './drag-engine';
type Engine = typeof import('./drag-engine');
export function touchCapable():boolean {return typeof window !== 'undefined' && typeof navigator !== 'undefined' && (navigator.maxTouchPoints > 0 || window.matchMedia('(any-pointer: coarse)').matches);}
/** Capability and lifetime are checked before importing or attaching listeners. */
export function createDragLoader(read:()=>Promise<Engine>) {
  let engine:Promise<Engine>|undefined;
  return (node:HTMLElement,parts:DragParts,capable:boolean)=>{
    let live = true, detach:(()=>void)|undefined;
    if (capable) {
      engine ??= read().catch(error=>{engine = undefined;throw error;});
      void engine.then(module=>{if (live) detach = module.attachDragDismiss(node,parts);},()=>{});
    }
    return ()=>{if (!live) return;live = false;detach?.();};
  };
}
export const attachTouchDismiss = createDragLoader(()=>import('./drag-engine'));
