import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { attachDragDismiss } from '../../packages/ui/src/foundation/drag-engine';
import { declaredSide, inverseRubberBand, nearbySide, ownsGesture, releaseVelocity, rubberBand, shouldDismiss } from '../../packages/ui/src/foundation/drag-math';
import { nextChoice } from '../../packages/ui/src/foundation/choice';
import { retainExit } from '../../packages/ui/src/foundation/presence';
import { stageSurfaceEntry } from '../../packages/ui/src/foundation/entrance';
import { surfacePointer } from './helpers/component-cascade.mjs';

const css = readFileSync(new URL('../styles/bt-motion.css',import.meta.url),'utf8');
const values = Object.fromEntries([...css.matchAll(/(--bt-(?:motion|ease)-[\w-]+):\s*([^;]+);/g)].map(match => [match[1],match[2]]));
let reduced = false;
class Styles {
  translate = ''; transition = ''; transform = ''; opacity = '';
  removeProperty(name:string) {if (name === 'translate' || name === 'transition' || name === 'transform' || name === 'opacity') this[name] = '';}
}
class Part extends EventTarget {
  style = new Styles(); dataset:Record<string,string> = {state:'open'};
  parentElement:Part|null = null; isConnected = true;
  tagName = 'DIV'; role = ''; editing = false; off = false; handle = false;
  scrollTop = 0; scrollLeft = 0; scrollHeight = 0; scrollWidth = 0; clientHeight = 0; clientWidth = 0;
  touchAction = 'auto'; overflowY = 'visible'; overflowX = 'visible'; direction = 'ltr'; entrance = '';
  visualTranslate:string|undefined;
  rect = {top:200,left:200,right:600,bottom:700,width:400,height:500};
  contains(target:Part):boolean {return target === this || (target.parentElement ? this.contains(target.parentElement) : false);}
  closest(selector:string):Part|null {
    if (selector === '[data-bt-drag-handle]' && this.handle) return this;
    if (selector.includes('input,textarea') && (['INPUT','TEXTAREA','SELECT'].includes(this.tagName) || this.editing || this.off || ['slider','textbox','combobox','spinbutton'].includes(this.role))) return this;
    return this.parentElement?.closest(selector) ?? null;
  }
  getBoundingClientRect() {return this.rect;}
  getAnimations() {return [];}
  setAttribute(name:string,value:string) {this.dataset[name.replace(/^data-/,'').replace(/-([a-z])/g,(_,letter:string)=>letter.toUpperCase())] = value;}
  removeAttribute(name:string) {delete this.dataset[name.replace(/^data-/,'').replace(/-([a-z])/g,(_,letter:string)=>letter.toUpperCase())];}
  toggleAttribute(name:string,on:boolean) {if (on) this.setAttribute(name,''); else this.removeAttribute(name);}
}
const element = (part:Part) => part as unknown as HTMLElement;
function touch(panel:Part,type:string,x:number,y:number,time:number,target:Part = panel):Event {
  const event = new Event(type,{cancelable:true});
  const point = {identifier:1,clientX:x,clientY:y};
  Object.defineProperties(event,{timeStamp:{value:time},target:{value:target},touches:{value:type === 'touchend' || type === 'touchcancel' ? [] : [point]},changedTouches:{value:[point]}});
  panel.dispatchEvent(event);return event;
}
function ended(panel:Part,propertyName = 'translate',target:Part = panel) {
  const event = new Event('transitionend');
  Object.defineProperties(event,{propertyName:{value:propertyName},target:{value:target}});panel.dispatchEvent(event);
}
let cleanups:Array<()=>void>;
beforeEach(() => {
  vi.useFakeTimers();reduced = false;cleanups = [];
  vi.stubGlobal('Element',Part);vi.stubGlobal('HTMLElement',Part);
  vi.stubGlobal('document',{documentElement:element(new Part())});
  vi.stubGlobal('window',{innerWidth:800,innerHeight:800,matchMedia:()=>({matches:reduced}),setTimeout,clearTimeout,requestAnimationFrame:(run:()=>void)=>setTimeout(run,0)});
  vi.stubGlobal('getComputedStyle',(part:Part)=>({
    translate:part.visualTranslate ?? (part.style.translate || 'none'), opacity:part.style.opacity || '1',touchAction:part.touchAction,overflowY:part.overflowY,overflowX:part.overflowX,direction:part.direction,
    getPropertyValue:(name:string)=>name === '--bt-sheet-from' ? part.entrance : values[name] ?? '',
  }));
});
afterEach(() => {for (const cleanup of cleanups) cleanup();vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals();});
function surface(allowed = true) {
  const panel = new Part(), shade = new Part(), dismiss = vi.fn(()=>{panel.isConnected = false;});
  panel.dataset.dismissSide = 'down';
  cleanups.push(attachDragDismiss(element(panel),{shade:()=>element(shade),dismiss,allowed:()=>allowed}));
  return {panel,shade,dismiss};
}

describe('gesture math and logical single-choice focus', () => {
  it('uses distance OR release flick, while a hold/reversal cannot inherit an old velocity', () => {
    expect(shouldDismiss(130,500,0)).toBe(true);expect(shouldDismiss(12,500,0.12)).toBe(true);
    expect(shouldDismiss(12,500,-1)).toBe(false);expect(shouldDismiss(-5,500,1)).toBe(false);
    expect(releaseVelocity([{t:0,travel:0},{t:10,travel:20}],20)).toBe(1);
    expect(releaseVelocity([{t:0,travel:0},{t:10,travel:20}],220)).toBe(0);
    expect(releaseVelocity([{t:0,travel:30},{t:50,travel:10}],60)).toBeLessThan(0);
    expect(releaseVelocity([],60)).toBe(0);
  });
  it('rubber bands continuously, with increasing resistance and invertible re-grab geometry', () => {
    const small = rubberBand(10,500), large = rubberBand(200,500);
    expect(small).toBeGreaterThan(0);expect(small).toBeLessThan(10);expect(large).toBeLessThan(200);
    expect(rubberBand(1000,500)).toBeLessThan(500);
    expect(inverseRubberBand(large,500)).toBeCloseTo(200);
    expect(rubberBand(0,500)).toBe(0);
  });
  it('follows declared logical sheet forms before inferring an undeclared popup edge', () => {
    expect(declaredSide('translateX(-1.5rem)')).toBe('left');expect(declaredSide('translateX(1rem)')).toBe('right');
    expect(declaredSide('translateY(1rem)')).toBe('down');expect(declaredSide('none')).toBeNull();
    expect(nearbySide(0,400,800)).toBe('left');expect(nearbySide(400,800,800)).toBe('right');expect(nearbySide(0,800,800)).toBe('down');
  });
  it('roves in LTR/RTL, skips disabled options and handles Home/End/all-disabled', () => {
    expect(nextChoice([false,true,false],0,'ArrowRight',false)).toBe(2);
    expect(nextChoice([false,false,false],0,'ArrowRight',true)).toBe(2);
    expect(nextChoice([false,true,false],2,'Home',false)).toBe(0);
    expect(nextChoice([false,true,false],0,'End',true)).toBe(2);
    expect(nextChoice([true,true],0,'ArrowLeft',false)).toBe(-1);
  });
});

describe('actual touch engine with bounded mocked geometry, not browser feel', () => {
  it('tracks one-to-one on the panel, derives shade from that progress and never uses parent variables', () => {
    const {panel,shade} = surface();touch(panel,'touchstart',10,10,0);
    const moved = touch(panel,'touchmove',10,50,100);
    expect(moved.defaultPrevented).toBe(true);expect(panel.style.translate).toBe('0px 40px');expect(shade.style.opacity).toBe('0.92');
    expect(panel.style.transition).toBe('none');expect(shade.style.transition).toBe('none');
  });
  it('wrong-direction tracking resists, then returns quickly without a keyframe', () => {
    const {panel,dismiss} = surface();touch(panel,'touchstart',10,100,0);touch(panel,'touchmove',10,60,100);
    expect(Number.parseFloat(panel.style.translate.split(' ')[1])).toBeGreaterThan(-40);
    touch(panel,'touchend',10,60,150);
    expect(panel.style.transition).toContain('var(--bt-motion-popover)');expect(dismiss).not.toHaveBeenCalled();
    ended(panel);expect(panel.style.translate).toBe('');
  });
  it('a short fast flick leaves on fresh viewport geometry and dismisses only at settle completion', () => {
    const {panel,dismiss} = surface();touch(panel,'touchstart',10,10,0);touch(panel,'touchmove',10,30,10);
    panel.rect = {...panel.rect,top:300};Object.assign(window,{innerHeight:600});
    touch(panel,'touchend',10,30,20);
    expect(panel.style.translate).toBe('0px 320px');expect(panel.style.transition).toContain('var(--bt-motion-overlay)');expect(dismiss).not.toHaveBeenCalled();
    ended(panel);expect(dismiss).toHaveBeenCalledOnce();
  });
  it('can catch an outgoing settle and reverse it instead of closing or jumping to zero', () => {
    const {panel,dismiss} = surface();touch(panel,'touchstart',10,10,0);touch(panel,'touchmove',10,150,100);touch(panel,'touchend',10,150,110);
    panel.visualTranslate = '0px 200px';ended(panel);expect(dismiss).not.toHaveBeenCalled();touch(panel,'touchstart',10,200,150);
    expect(panel.style.translate).toBe('0px 200px');panel.visualTranslate = undefined;
    touch(panel,'touchmove',10,100,250);expect(panel.style.translate).toBe('0px 100px');
    touch(panel,'touchend',10,100,260);ended(panel);vi.runAllTimers();
    expect(dismiss).not.toHaveBeenCalled();expect(panel.style.translate).toBe('');
  });
  it('honors close guards, keeps reduced tracking and settles reduced release immediately', () => {
    const guarded = surface(false);touch(guarded.panel,'touchstart',0,0,0);touch(guarded.panel,'touchmove',0,200,100);touch(guarded.panel,'touchend',0,200,110);ended(guarded.panel);
    expect(guarded.dismiss).not.toHaveBeenCalled();
    const reducedSurface = surface();reduced = true;
    touch(reducedSurface.panel,'touchstart',0,0,0);touch(reducedSurface.panel,'touchmove',0,40,10);
    expect(reducedSurface.panel.style.translate).toBe('0px 40px');touch(reducedSurface.panel,'touchend',0,40,20);
    expect(reducedSurface.dismiss).toHaveBeenCalledOnce();
  });
  it('leaves fields, axis owners, scrolling content and nested surfaces their own gesture', () => {
    for (const kind of ['field','axis','scroll']) {
      const {panel} = surface(), child = new Part();child.parentElement = panel;
      if (kind === 'field') child.tagName = 'INPUT';
      if (kind === 'axis') child.touchAction = 'pan-x';
      if (kind === 'scroll') {child.overflowY = 'auto';child.scrollTop = 20;child.scrollHeight = 1000;child.clientHeight = 200;}
      touch(panel,'touchstart',0,0,0,child);touch(panel,'touchmove',0,50,100,child);
      expect(panel.style.translate).toBe('');
    }
    const {panel:outer} = surface(), {panel:inner} = surface();inner.parentElement = outer;
    expect(ownsGesture(element(outer),element(inner),{has:node=>node === element(inner)})).toBe(false);
    touch(outer,'touchstart',0,0,0,inner);touch(outer,'touchmove',0,50,100,inner);expect(outer.style.translate).toBe('');
  });
});

describe('transition-aware exit ownership', () => {
  it('ignores child/unrelated events, completes once and cancels stale reopen callbacks', () => {
    const panel = new Part(), child = new Part(), first = vi.fn();
    const cancel = retainExit(element(panel),first);
    ended(panel,'opacity',child);ended(panel,'width');expect(first).not.toHaveBeenCalled();
    cancel();ended(panel,'opacity');vi.runAllTimers();expect(first).not.toHaveBeenCalled();
    const second = vi.fn();cleanups.push(retainExit(element(panel),second));ended(panel,'transform');expect(second).not.toHaveBeenCalled();panel.style.opacity = '0';ended(panel,'opacity');ended(panel,'transform');vi.runAllTimers();expect(second).toHaveBeenCalledOnce();
  });
  it('bounds missing events using current CSS duration and reduced mode lands without a hold', () => {
    const panel = new Part(), finish = vi.fn();cleanups.push(retainExit(element(panel),finish));
    vi.advanceTimersByTime(239);expect(finish).not.toHaveBeenCalled();vi.advanceTimersByTime(1);expect(finish).toHaveBeenCalledOnce();
    reduced = true;const immediate = vi.fn();cleanups.push(retainExit(element(panel),immediate));vi.runAllTimers();expect(immediate).toHaveBeenCalledOnce();
  });
});


describe('actual first-frame fallback lifecycle with bounded frame scheduling',()=>{
  function scheduler() {
    const frames = new Map<number,FrameRequestCallback>();let serial = 0;
    Object.assign(window,{requestAnimationFrame:(run:FrameRequestCallback)=>{frames.set(++serial,run);return serial;},cancelAnimationFrame:(id:number)=>frames.delete(id)});
    return {frames,frame:()=>{const pending = [...frames.values()];frames.clear();for (const run of pending) run(0);}};
  }
  it('stages paired unsupported-engine parts once, then releases their accepted CSS recipe together',()=>{
    const clock = scheduler(), panel = new Part(), shade = new Part();cleanups.push(stageSurfaceEntry([element(panel),element(shade)],()=> 'pointer'));
    expect(panel.dataset).toHaveProperty('starting');expect(shade.dataset).toHaveProperty('starting');clock.frame();expect(panel.dataset).toHaveProperty('starting');clock.frame();expect(panel.dataset).not.toHaveProperty('starting');expect(shade.dataset).not.toHaveProperty('starting');expect(clock.frames.size).toBe(0);
  });
  it('preserves native starting-style and bypasses all scheduled work for keyboard/off/reduced input',()=>{
    const clock = scheduler(), panel = new Part();
    Object.assign(window,{CSSStartingStyleRule:class {}});stageSurfaceEntry([element(panel)],()=> 'pointer');expect(clock.frames.size).toBe(0);Reflect.deleteProperty(window,'CSSStartingStyleRule');
    for (const input of ['keyboard','off']) stageSurfaceEntry([element(panel)],()=>input);
    reduced = true;stageSurfaceEntry([element(panel)],()=> 'pointer');expect(panel.dataset).not.toHaveProperty('starting');expect(clock.frames.size).toBe(0);
  });
  it('cancels close/unmount and stale frame owners without clearing a reopened first frame',()=>{
    const clock = scheduler(), panel = new Part(), first = stageSurfaceEntry([element(panel)],()=> 'pointer');clock.frame();panel.dataset.state = 'closed';first();expect(clock.frames.size).toBe(0);expect(panel.dataset).not.toHaveProperty('starting');
    panel.dataset.state = 'open';const second = stageSurfaceEntry([element(panel)],()=> 'pointer');first();expect(panel.dataset).toHaveProperty('starting');panel.isConnected = false;clock.frame();expect(panel.dataset).not.toHaveProperty('starting');expect(clock.frames.size).toBe(0);second();
  });
  it('a pointer close leaves the next press available during the retained exit, and reopen cancels old work',()=>{
    const clock = scheduler(), panel = new Part(), shade = new Part(), trigger = new Part(), finished = vi.fn();
    const first = stageSurfaceEntry([element(panel),element(shade)],()=> 'pointer');panel.dataset.state = shade.dataset.state = 'closed';first();const stopExit = retainExit(element(panel),finished);
    expect(surfacePointer(['bt-shade','bt-surface-shade'],'closed')).toBe('none');expect(surfacePointer(['bt-window','bt-surface-panel'],'closed')).toBe('none');
    trigger.addEventListener('click',()=>{stopExit();panel.dataset.state = shade.dataset.state = 'open';cleanups.push(stageSurfaceEntry([element(panel),element(shade)],()=> 'pointer'));});
    // Route the next press using the actual imported source cascade, not a browser hit-test claim.
    if (surfacePointer(['bt-shade','bt-surface-shade'],'closed') === 'none') trigger.dispatchEvent(new Event('click'));
    expect(panel.dataset.state).toBe('open');clock.frame();clock.frame();vi.runAllTimers();expect(finished).not.toHaveBeenCalled();expect(panel.dataset).not.toHaveProperty('starting');
  });
  it('a mode change or close before the queued frame removes hidden start states immediately at the next frame',()=>{
    const clock = scheduler(), panel = new Part();let input = 'pointer';stageSurfaceEntry([element(panel)],()=>input);input = 'keyboard';clock.frame();expect(panel.dataset).not.toHaveProperty('starting');expect(clock.frames.size).toBe(0);
    input = 'pointer';stageSurfaceEntry([element(panel)],()=>input);panel.dataset.state = 'closed';clock.frame();expect(panel.dataset).not.toHaveProperty('starting');expect(clock.frames.size).toBe(0);
  });
});
