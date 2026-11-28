import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { lockSurfaceScroll } from '../../packages/ui/src/foundation/surface-scroll';
import { shouldRestoreSurfaceFocus } from '../../packages/ui/src/foundation/surface-focus';
import { attachToastReach } from '../../packages/ui/src/foundation/toast-reach';
import { reserveToastSpace } from '../../packages/ui/src/foundation/toast-room';
import { keepToastPress } from '../../packages/ui/src/foundation/surface-context';
class Part extends EventTarget {
  parentElement:Part|null = null;dataset:Record<string,string> = {};isConnected = true;toast = false;dialog = false;hasNotice = false;active = false;scrollHeight = 100;clientHeight = 100;scrollTop = 0;clientWidth = 800;overflowY = 'visible';bottom = '16px';basePadding = '8px';
  style = {overflow:'',paddingInlineEnd:'',paddingBlockEnd:''};
  contains(target:Part):boolean {return target === this || Boolean(target.parentElement && this.contains(target.parentElement));}
  closest(selector:string):Part|null {if (selector.includes('data-bt-toast-region') && this.toast || selector.includes('role="dialog"') && this.dialog) return this;return this.parentElement?.closest(selector) ?? null;}
  querySelector(selector:string) {return selector === '[data-bt-toast]' && this.hasNotice ? this : null;}
  hasAttribute(name:string) {return name === 'data-active' && this.active;}
  focus = vi.fn(()=>{doc.activeElement = this;emit('focusin',this);});
}
class Watch {
  static all:Watch[] = [];callback:()=>void;observe = vi.fn();disconnect = vi.fn();
  constructor(callback:()=>void) {this.callback = callback;Watch.all.push(this);}
}
let win:EventTarget & {innerWidth:number;setTimeout:typeof setTimeout;clearTimeout:typeof clearTimeout};
let doc:{body:Part;documentElement:Part;activeElement:Part|null;scrollingElement:Part|null;querySelector:(selector:string)=>Part|null};
let release:(()=>void)|undefined;
const element = (part:Part)=>part as unknown as HTMLElement;
function emit(type:string,target:Part|null,props:Record<string,unknown> = {}) {const event = new Event(type,{cancelable:true});Object.defineProperties(event,Object.fromEntries(Object.entries({target,...props}).map(([key,value])=>[key,{value}])));win.dispatchEvent(event);return event;}
beforeEach(()=>{
  vi.useFakeTimers();Watch.all = [];release = undefined;win = Object.assign(new EventTarget(),{innerWidth:820,setTimeout,clearTimeout});const body = new Part(), root = new Part();doc = {body,documentElement:root,activeElement:body,scrollingElement:root,querySelector:()=>null};
  vi.stubGlobal('window',win);vi.stubGlobal('document',doc);vi.stubGlobal('Element',Part);vi.stubGlobal('HTMLElement',Part);vi.stubGlobal('MutationObserver',Watch);
  vi.stubGlobal('getComputedStyle',(part:Part)=>({paddingInlineEnd:'12px',paddingBlockEnd:part.style.paddingBlockEnd || part.basePadding,bottom:part.bottom,overflowY:part.overflowY}));
});
afterEach(()=>{release?.();vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals();});
describe('logical-open scroll and focus ownership',()=>{
  it('refcounts nested scroll ownership and restores exact inline values only after the last close',()=>{
    doc.body.style.overflow = 'auto';doc.body.style.paddingInlineEnd = '3px';const first = lockSurfaceScroll(), second = lockSurfaceScroll();expect(doc.body.style.overflow).toBe('hidden');expect(doc.body.style.paddingInlineEnd).toBe('32px');first();first();expect(doc.body.style.overflow).toBe('hidden');second();expect(doc.body.style).toMatchObject({overflow:'auto',paddingInlineEnd:'3px'});
  });
  it('does not add padding when no scrollbar gap exists',()=>{win.innerWidth = 800;doc.body.style.paddingInlineEnd = '7px';release = lockSurfaceScroll();expect(doc.body.style.paddingInlineEnd).toBe('7px');});
  it('returns from the old panel/body but never steals a newer outside click or nonmodal Tab destination',()=>{
    const panel = new Part(), child = new Part(), outside = new Part();child.parentElement = panel;expect(shouldRestoreSurfaceFocus(element(child),element(panel))).toBe(true);expect(shouldRestoreSurfaceFocus(element(doc.body),null)).toBe(true);expect(shouldRestoreSurfaceFocus(element(outside),element(panel))).toBe(false);
  });
});
describe('toast keyboard bridge and modal-safe pointer actions',()=>{
  function setup() {const region = new Part(), field = new Part(), dialog = new Part();region.toast = true;region.hasNotice = true;dialog.dialog = true;field.parentElement = dialog;doc.activeElement = field;const change = vi.fn(), reach = attachToastReach(()=>element(region),change);release = reach.dispose;return {region,field,change,reach};}
  it('intercepts Alt+T but focuses only after the public bridge commits, including repeated pending entry',()=>{
    const {region,field,change,reach} = setup();const first = emit('keydown',field,{altKey:true,code:'KeyT'});emit('keydown',field,{altKey:true,code:'KeyT'});expect(first.defaultPrevented).toBe(true);expect(region.focus).not.toHaveBeenCalled();expect(change).toHaveBeenCalledExactlyOnceWith(true);reach.commit();expect(region.focus).toHaveBeenCalledOnce();expect(doc.activeElement).toBe(region);expect(region.dataset.btMotionInput).toBe('keyboard');emit('keydown',region,{altKey:true,code:'KeyT'});expect(region.focus).toHaveBeenCalledTimes(2);
  });
  it('Escape restores the modal field and does not dismiss its layer',()=>{
    const {region,field,change,reach} = setup();emit('keydown',field,{altKey:true,code:'KeyT'});reach.commit();const escape = emit('keydown',region,{key:'Escape'});expect(escape.defaultPrevented).toBe(true);expect(doc.activeElement).toBe(region);vi.runAllTimers();expect(doc.activeElement).toBe(field);expect(change).toHaveBeenLastCalledWith(false);expect(Watch.all[0].disconnect).toHaveBeenCalled();
  });
  it('pointer actions keep invoking focus and cancel outside dismissal without creating a bridge',()=>{
    const {region,field,change} = setup();const action = new Part();action.parentElement = region;emit('pointerdown',action);const press = emit('mousedown',action);expect(press.defaultPrevented).toBe(true);expect(doc.activeElement).toBe(field);expect(change).not.toHaveBeenCalled();expect(region.dataset.btMotionInput).toBe('pointer');const preventDefault = vi.fn();keepToastPress({target:element(action),preventDefault});expect(preventDefault).toHaveBeenCalledOnce();
  });
  it('returns focus when a focused toast is removed and cleans queued return on unmount',()=>{
    const {region,field,reach} = setup();emit('keydown',field,{altKey:true,code:'KeyT'});reach.commit();doc.activeElement = doc.body;Watch.all[0].callback();expect(doc.activeElement).toBe(field);emit('keydown',field,{altKey:true,code:'KeyT'});reach.commit();emit('keydown',region,{key:'Escape'});const before = field.focus.mock.calls.length;reach.dispose();vi.runAllTimers();expect(field.focus).toHaveBeenCalledTimes(before);expect(vi.getTimerCount()).toBe(0);
  });
  it('supports the frozen notification stack only when the canonical queue is empty',()=>{
    const {region,field,reach} = setup(), old = new Part();old.toast = true;region.hasNotice = false;doc.querySelector = ()=>old;emit('keydown',field,{altKey:true,code:'KeyT'});reach.commit();expect(old.focus).toHaveBeenCalledOnce();expect(region.focus).not.toHaveBeenCalled();
  });
});
describe('discrete toast room measurement',()=>{
  it('reserves only caller-owned content and restores exact padding without cumulative growth',()=>{
    const region = new Part(), content = new Part();region.active = true;region.clientHeight = 100;content.style.paddingBlockEnd = '10px';const room = reserveToastSpace(element(region),()=>element(content));release = room.restore;room.measure();expect(content.style.paddingBlockEnd).toBe('126px');room.measure();expect(content.style.paddingBlockEnd).toBe('126px');region.active = false;room.measure();expect(content.style.paddingBlockEnd).toBe('10px');room.restore();expect(content.style.paddingBlockEnd).toBe('10px');
  });
  it('keeps a reader at the scroll foot, and releases a previously owned scope on replacement',()=>{
    const region = new Part(), first = new Part(), second = new Part();region.active = true;region.clientHeight = 80;first.overflowY = 'auto';first.clientHeight = 100;first.scrollHeight = 500;first.scrollTop = 400;let owner = first;const room = reserveToastSpace(element(region),()=>element(owner));release = room.restore;room.measure();expect(first.scrollTop).toBe(500);owner = second;room.measure();expect(first.style.paddingBlockEnd).toBe('');expect(second.style.paddingBlockEnd).toBe('104px');
  });
});
