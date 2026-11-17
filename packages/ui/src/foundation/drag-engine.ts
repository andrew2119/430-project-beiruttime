import { readMotionToken } from '../motion-tokens';
import { declaredSide, inverseRubberBand, nearbySide, ownsGesture, releaseVelocity, rubberBand, shouldDismiss, type DismissSide, type TravelSample } from './drag-math';

export type DragParts = {shade:()=>HTMLElement|null; dismiss:()=>void; allowed:(event:TouchEvent)=>boolean; scrollBoundary?:()=>HTMLElement|null};
const attached = new WeakSet<Element>();
const noStart = 'input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"],[role="combobox"],[role="spinbutton"],[role="slider"],[data-drag-dismiss="off"]';
const vertical = (side:DismissSide) => side === 'down';
const sign = (side:DismissSide) => side === 'left' ? -1 : 1;

function writeTranslation(node:HTMLElement, x:number, y:number) {node.style.translate = `${x}px ${y}px`;}
function writeOpacity(node:HTMLElement|null, opacity:number) {if (node) node.style.opacity = String(Math.max(0,Math.min(1,opacity)));}
function currentOffset(node:HTMLElement, side:DismissSide): number {
  const parts = getComputedStyle(node).translate.split(/\s+/);
  const value = Number.parseFloat(parts[vertical(side) ? 1 : 0] ?? '0');
  return Number.isFinite(value) ? sign(side) * value : 0;
}
function captureTransitions(node:HTMLElement|null) {
  for (const animation of node?.getAnimations() ?? []) {
    try {animation.commitStyles(); animation.cancel();} catch {animation.cancel();}
  }
}
function scrollerTakes(target:Element, panel:HTMLElement, side:DismissSide, delta:number): boolean {
  for (let node:Element|null = target; node; node = node.parentElement) {
    const css = getComputedStyle(node), y = vertical(side);
    if (/auto|scroll/.test(y ? css.overflowY : css.overflowX)) {
      const rtl = !y && css.direction === 'rtl';
      const position = y ? node.scrollTop : rtl ? Math.abs(node.scrollLeft) : node.scrollLeft;
      const limit = y ? node.scrollHeight-node.clientHeight : node.scrollWidth-node.clientWidth;
      const travel = rtl ? -delta : delta;
      if (limit > 1 && (travel > 0 ? position > 0.5 : position < limit-0.5)) return true;
    }
    if (node === panel) break;
  }
  return false;
}
function axisAllowed(target:Element, panel:HTMLElement, side:DismissSide): boolean {
  if (target.closest('[data-bt-drag-handle]')) return true;
  for (let node:Element|null = target; node; node = node.parentElement) {
    const action = getComputedStyle(node).touchAction;
    if (action && !['auto','manipulation'].includes(action) && !(vertical(side) ? /pan-y|pan-up|pan-down/ : /pan-x|pan-left|pan-right/).test(action)) return false;
    if (node === panel) break;
  }
  return true;
}

type Gesture = {id:number; target:Element; x:number; y:number; carried:number; side:DismissSide; size:number; offset:number; top:number; dragging:boolean; samples:TravelSample[]};

/** Loaded only for a touch-capable open surface. Tracking writes on the two
 * actual parts, never React state or an inherited variable on their parent. */
export function attachDragDismiss(panel:HTMLElement, parts:DragParts): ()=>void {
  const shade = parts.shade();
  let gesture:Gesture|null = null;
  let settle:{cancel:()=>void; kind:'back'|'out'}|null = null;
  let live = true, suppressClickAt = -Infinity;
  const offset = (side:DismissSide, value:number) => writeTranslation(panel, vertical(side) ? 0 : sign(side)*value, vertical(side) ? value : 0);
  const stopSettle = () => {settle?.cancel(); settle = null;};
  const clean = () => {
    panel.style.removeProperty('translate'); panel.style.removeProperty('transition'); panel.style.removeProperty('transform'); panel.style.removeProperty('opacity');
    shade?.style.removeProperty('transition'); shade?.style.removeProperty('opacity');
    panel.removeAttribute('data-bt-dragging'); panel.removeAttribute('data-drag-leave'); shade?.removeAttribute('data-drag-leave');
  };
  const still = () => {
    captureTransitions(panel); captureTransitions(shade);
    panel.style.transition = 'none'; if (shade) shade.style.transition = 'none';
  };
  const settleTo = (kind:'back'|'out', side:DismissSide, target:number) => {
    stopSettle();
    const duration = readMotionToken(kind === 'out' ? '--bt-motion-overlay' : '--bt-motion-popover',panel) ?? 0;
    panel.toggleAttribute('data-drag-leave',kind === 'out'); shade?.toggleAttribute('data-drag-leave',kind === 'out');
    panel.style.transition = duration === 0 ? 'none' : kind === 'out' ? 'translate var(--bt-motion-overlay) var(--bt-ease-drawer), transform var(--bt-motion-overlay) var(--bt-ease-drawer), opacity var(--bt-motion-overlay) var(--bt-ease-drawer)' : 'translate var(--bt-motion-popover) var(--bt-ease-drawer), transform var(--bt-motion-popover) var(--bt-ease-drawer), opacity var(--bt-motion-popover) var(--bt-ease-drawer)';
    if (shade) shade.style.transition = duration === 0 ? 'none' : kind === 'out' ? 'opacity var(--bt-motion-overlay) var(--bt-ease-drawer)' : 'opacity var(--bt-motion-popover) var(--bt-ease-drawer)';
    panel.style.removeProperty('transform'); panel.style.removeProperty('opacity');
    offset(side,target); writeOpacity(shade,kind === 'out' ? 0 : 1);
    if (kind === 'out') writeOpacity(panel,0);
    let current = true, timer:number|undefined;
    const cancel = () => {current = false; if (timer !== undefined) window.clearTimeout(timer); panel.removeEventListener('transitionend',ended);};
    const finish = () => {
      if (!current || !live) return;
      cancel(); settle = null;
      if (kind === 'back') {clean(); return;}
      parts.dismiss();
      // A controlled parent may refuse a close. Restore it, not a hidden panel.
      window.requestAnimationFrame(() => {if (live && panel.isConnected && panel.dataset.state === 'open' && !gesture) settleTo('back',side,0);});
    };
    const ended = (event:TransitionEvent) => {if (event.target === panel && event.propertyName === 'translate' && Math.abs(currentOffset(panel,side)-target) < 0.5) finish();};
    settle = {kind,cancel};
    panel.addEventListener('transitionend',ended);
    if (duration === 0) finish(); else timer = window.setTimeout(finish,duration*2);
  };
  const start = (event:TouchEvent) => {
    if (event.touches.length !== 1) {if (gesture?.dragging) settleTo('back',gesture.side,0); gesture = null; return;}
    if (panel.dataset.state !== 'open') return;
    const target = event.target instanceof Element ? event.target : null;
    if (!target || target.closest(noStart) || !ownsGesture(panel,target,attached)) return;
    const rect = panel.getBoundingClientRect();
    const side = panel.dataset.dismissSide === 'down' ? 'down' : declaredSide(getComputedStyle(panel).getPropertyValue('--bt-sheet-from')) ?? nearbySide(rect.left,rect.right,window.innerWidth);
    if (!axisAllowed(target,panel,side)) return;
    const caught = !!settle, value = caught ? currentOffset(panel,side) : 0;
    const shown = Number.parseFloat(shade ? getComputedStyle(shade).opacity : '1');
    const size = Math.max(1, vertical(side) ? rect.height : rect.width);
    const top = Math.min(1,(Number.isFinite(shown) ? shown : 1) / Math.max(0.01,1-Math.max(0,value)/size));
    if (caught) {still(); stopSettle(); offset(side,value); writeOpacity(shade,top*(1-Math.max(0,value)/size));}
    const touch = event.touches[0], carried = value < 0 ? -inverseRubberBand(-value,size) : value;
    gesture = {id:touch.identifier,target,x:touch.clientX,y:touch.clientY,carried,side,size,offset:value,top,dragging:caught,samples:[{t:event.timeStamp,travel:carried}]};
  };
  const move = (event:TouchEvent) => {
    const g = gesture;
    if (!g) return;
    const touch = [...event.touches].find(value => value.identifier === g.id);
    if (!touch) return;
    const dx = touch.clientX-g.x, dy = touch.clientY-g.y, along = vertical(g.side) ? dy : dx, across = vertical(g.side) ? dx : dy;
    if (!g.dragging) {
      if (Math.max(Math.abs(dx),Math.abs(dy)) < 4) return;
      if (Math.abs(across) > Math.abs(along) || scrollerTakes(g.target,parts.scrollBoundary?.() ?? panel,g.side,along)) {gesture = null; return;}
      const rect = panel.getBoundingClientRect();
      g.size = Math.max(1,vertical(g.side) ? rect.height : rect.width);
      const shown = Number.parseFloat(shade ? getComputedStyle(shade).opacity : '1');
      g.top = Number.isFinite(shown) ? shown : 1;
      still(); g.dragging = true;
    }
    if (event.cancelable) event.preventDefault();
    panel.setAttribute('data-bt-dragging','');
    const travel = g.carried + sign(g.side)*along;
    g.offset = travel < 0 ? -rubberBand(-travel,g.size) : travel;
    offset(g.side,g.offset); writeOpacity(shade,g.top*(1-Math.max(0,g.offset)/g.size));
    g.samples.push({t:event.timeStamp,travel});
    while (g.samples.length > 2 && event.timeStamp-g.samples[0].t > 100) g.samples.shift();
  };
  const end = (event:TouchEvent) => {
    const g = gesture;
    if (!g || ![...event.changedTouches].some(touch => touch.identifier === g.id)) return;
    gesture = null;
    if (!g.dragging) return;
    suppressClickAt = event.timeStamp;
    const leaving = event.type === 'touchend' && shouldDismiss(g.offset,g.size,releaseVelocity(g.samples,event.timeStamp)) && parts.allowed(event);
    if (!leaving) {settleTo('back',g.side,0); return;}
    // Read the current box at release, not the position captured on touchstart.
    const rect = panel.getBoundingClientRect();
    const away = g.side === 'down' ? window.innerHeight-rect.top+g.offset : g.side === 'left' ? rect.right+g.offset : window.innerWidth-rect.left+g.offset;
    settleTo('out',g.side,Math.max(g.offset,away));
  };
  const click = (event:MouseEvent) => {if (event.detail > 0 && event.timeStamp-suppressClickAt < 600) {event.preventDefault(); event.stopPropagation();}};
  attached.add(panel);
  panel.addEventListener('touchstart',start,{passive:true}); panel.addEventListener('touchmove',move,{passive:false});
  panel.addEventListener('touchend',end,{passive:true}); panel.addEventListener('touchcancel',end,{passive:true}); panel.addEventListener('click',click,true);
  return () => {live = false; gesture = null; stopSettle(); attached.delete(panel); panel.removeEventListener('touchstart',start); panel.removeEventListener('touchmove',move); panel.removeEventListener('touchend',end); panel.removeEventListener('touchcancel',end); panel.removeEventListener('click',click,true); clean();};
}
