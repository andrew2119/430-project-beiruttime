import { inToastRegion } from './surface-context';
import { markMotionInput } from '../motion-tokens';
/** Keyboard entry waits for the public focus bridge to mount. Pointer actions
 * never release the underlying modal's focus owner. */
export function attachToastReach(region:()=>HTMLElement|null,change:(reaching:boolean)=>void) {
  let on = false, committed = false, pendingFocus:(()=>void)|undefined, cameFrom:HTMLElement|null = null, watch:MutationObserver|undefined, returnTimer:number|undefined;
  const set = (next:boolean,pending?:()=>void) => {
    if (on === next) {if (pending) {if (committed) pending();else pendingFocus = pending;}return;}
    on = next;committed = false;pendingFocus = pending;watch?.disconnect();watch = undefined;change(next);
    if (next) {
      watch = new MutationObserver(()=>{
        const active = document.activeElement;
        if (active && active !== document.body && active.isConnected) return;
        if (cameFrom?.isConnected) cameFrom.focus({preventScroll:true});else set(false);
      });
      watch.observe(document.body,{childList:true,subtree:true});
    }
  };
  const pointer = (event:PointerEvent) => {const own = region();if (event.target instanceof Element && own?.contains(event.target)) markMotionInput(own,'pointer');};
  const mouse = (event:MouseEvent) => {if (inToastRegion(event.target) && document.activeElement?.closest('[role="dialog"],[role="alertdialog"]') && !inToastRegion(document.activeElement)) event.preventDefault();};
  const inside = (event:FocusEvent) => {if (!inToastRegion(event.target)) set(false);};
  const key = (event:KeyboardEvent) => {
    if (event.altKey && event.code === 'KeyT') {
      const own = region(), target = own?.querySelector('[data-bt-toast]') ? own : document.querySelector<HTMLElement>('[data-sonner-toaster]');
      if (!target) return;
      if (!on) cameFrom = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      event.preventDefault();event.stopPropagation();if (target === own) markMotionInput(target,'keyboard');
      set(true,()=>{if (target.isConnected) target.focus({preventScroll:true});else set(false);});
    } else if (on && event.key === 'Escape' && inToastRegion(document.activeElement)) {
      event.preventDefault();event.stopPropagation();const back = cameFrom;
      if (returnTimer !== undefined) window.clearTimeout(returnTimer);
      returnTimer = window.setTimeout(()=>{returnTimer = undefined;if (!inToastRegion(document.activeElement)) return;if (back?.isConnected) back.focus({preventScroll:true});else set(false);},0);
    }
  };
  window.addEventListener('pointerdown',pointer,true);window.addEventListener('mousedown',mouse,true);window.addEventListener('focusin',inside,true);window.addEventListener('keydown',key,true);
  return {
    commit:()=>{if (on) {committed = true;const focus = pendingFocus;pendingFocus = undefined;focus?.();}},
    dispose:()=>{pendingFocus = undefined;watch?.disconnect();if (returnTimer !== undefined) window.clearTimeout(returnTimer);window.removeEventListener('pointerdown',pointer,true);window.removeEventListener('mousedown',mouse,true);window.removeEventListener('focusin',inside,true);window.removeEventListener('keydown',key,true);},
  };
}
