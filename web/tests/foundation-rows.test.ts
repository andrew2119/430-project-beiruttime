import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { createRowBatch, matrixTranslation } from '../../packages/ui/src/foundation/row-motion';
import type { ListKey, RowPhase } from '../../packages/ui/src/foundation/list-model';
const css = readFileSync(new URL('../styles/bt-motion.css',import.meta.url),'utf8');
const values = Object.fromEntries([...css.matchAll(/(--bt-motion-[\w-]+):\s*([^;]+);/g)].map(match=>[match[1],match[2]]));
class Row extends EventTarget {
  flags = new Set<string>();writes:string[] = [];x = 0;y = 0;width = 400;visualTransform = 'none';visualOpacity = '1';
  style = {transform:'',opacity:'',transition:'',removeProperty:(name:string)=>{this.writes.push(`remove:${name}`);if (name === 'transform' || name === 'opacity' || name === 'transition') this.style[name] = '';}};
  animations:Array<{commitStyles:()=>void;cancel:()=>void}> = [];
  offsetWidth = 400;
  constructor() {super();for (const property of ['transform','opacity','transition'] as const) {let value = '';Object.defineProperty(this.style,property,{get:()=>value,set:(next:string)=>{value = next;this.writes.push(`${property}:${next}`);}});}}
  getBoundingClientRect() {return {left:this.x,top:this.y,width:this.width};}
  getAnimations() {return this.animations;}
  setAttribute(name:string) {this.flags.add(name);}
  removeAttribute(name:string) {this.flags.delete(name);}
}
const element = (row:Row)=>row as unknown as HTMLElement;
const phases = (values:Array<[ListKey,RowPhase]>)=>new Map(values);
function end(row:Row,type:'animationend'|'transitionend',property:string,target:Row = row) {const event = new Event(type);Object.defineProperties(event,{target:{value:target},animationName:{value:property},propertyName:{value:property}});row.dispatchEvent(event);}
let batch:ReturnType<typeof createRowBatch>;
beforeEach(()=>{
  vi.useFakeTimers();batch = createRowBatch();
  vi.stubGlobal('window',{matchMedia:()=>({matches:false}),setTimeout,clearTimeout});vi.stubGlobal('document',{documentElement:{}});
  vi.stubGlobal('getComputedStyle',(row:Row)=>({transform:row.visualTransform,opacity:row.visualOpacity,getPropertyValue:(name:string)=>values[name] ?? ''}));
});
afterEach(()=>{batch.dispose();vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals();});
describe('native row batch with mocked current visual geometry',()=>{
  it('reads both matrix forms and fails closed for invalid transforms',()=>{expect(matrixTranslation('matrix(1,0,0,1,3,-8)')).toEqual({x:3,y:-8});expect(matrixTranslation('matrix3d(1,0,0,0,0,1,0,0,0,0,1,0,12,24,0,1)')).toEqual({x:12,y:24});expect(matrixTranslation('matrix(bad)')).toEqual({x:0,y:0});});
  it('cancels a still-running entry before holding its current transform for exit',()=>{
    const root = new Row(), a = new Row(), c = new Row(), nodes = new Map<ListKey,HTMLElement>([['a',element(a)]]), finish = vi.fn();
    batch.update(element(root),nodes,['a'],phases([['a','steady']]),true,finish);
    nodes.set('c',element(c));c.y = 100;batch.update(element(root),nodes,['a','c'],phases([['a','steady'],['c','enter']]),false,finish);expect(c.flags.has('data-enter')).toBe(true);
    const animation = {commitStyles:vi.fn(),cancel:vi.fn()};c.animations = [animation];c.visualOpacity = '0.42';c.visualTransform = 'matrix(1,0,0,1,0,8)';c.y = 108;
    batch.update(element(root),nodes,['a','c'],phases([['a','steady'],['c','exit']]),false,finish);
    expect(animation.commitStyles).toHaveBeenCalledOnce();expect(animation.cancel).toHaveBeenCalledOnce();expect(c.flags.has('data-enter')).toBe(false);expect(c.flags.has('data-exit')).toBe(true);expect(c.style.transform).toBe('translate(0px, 8px)');expect(c.writes).toContain('opacity:0.42');
    end(c,'animationend','bt-row-in');expect(c.flags.has('data-exit')).toBe(true);expect(finish).not.toHaveBeenCalled();
    end(c,'transitionend','opacity',a);expect(finish).not.toHaveBeenCalled();c.visualOpacity = '0';end(c,'transitionend','opacity');expect(finish).toHaveBeenCalledExactlyOnceWith('c');
  });
  it('undo during exit starts at its current pixels and rejects old callbacks and unrelated events',()=>{
    const root = new Row(), a = new Row(), nodes = new Map<ListKey,HTMLElement>([['a',element(a)]]), finish = vi.fn();batch.update(element(root),nodes,['a'],phases([['a','steady']]),true,finish);
    batch.update(element(root),nodes,['a'],phases([['a','exit']]),false,finish);a.visualOpacity = '0.3';a.visualTransform = 'matrix(1,0,0,1,0,0)';
    batch.update(element(root),nodes,['a'],phases([['a','resume']]),false,finish);expect(a.flags.has('data-exit')).toBe(false);expect(a.flags.has('data-resume')).toBe(true);expect(a.writes).toContain('opacity:0.3');expect(a.flags.has('data-enter')).toBe(false);
    end(a,'transitionend','opacity');expect(a.flags.has('data-resume')).toBe(true);a.visualOpacity = '1';end(a,'transitionend','width');expect(a.flags.has('data-resume')).toBe(true);end(a,'transitionend','opacity');expect(a.flags.size).toBe(0);vi.runAllTimers();expect(finish).not.toHaveBeenCalled();
  });
  it('closes the removed gap only at completion then FLIPs remaining rows, with immediate keyboard cleanup',()=>{
    const root = new Row(), a = new Row(), b = new Row();b.y = 100;const nodes = new Map<ListKey,HTMLElement>([['a',element(a)],['b',element(b)]]), finish = vi.fn();batch.update(element(root),nodes,['a','b'],phases([['a','steady'],['b','steady']]),true,finish);
    batch.update(element(root),nodes,['a','b'],phases([['a','exit'],['b','steady']]),false,finish);expect(b.style.transform).toBe('');vi.advanceTimersByTime(240);expect(finish).toHaveBeenCalledExactlyOnceWith('a');
    nodes.delete('a');batch.remove('a');b.y = 0;batch.update(element(root),nodes,['b'],phases([['b','steady']]),false,finish);expect(b.flags.has('data-reorder')).toBe(true);expect(b.writes).toContain('transform:translate(0px, 100px)');
    batch.update(element(root),nodes,['b'],phases([['b','steady']]),true,finish);expect(b.flags.size).toBe(0);expect(vi.getTimerCount()).toBe(0);
  });
  it('refreshes geometry after a discrete resize without creating a phantom reorder',()=>{
    const root = new Row(), a = new Row(), b = new Row();b.y = 100;const nodes = new Map<ListKey,HTMLElement>([['a',element(a)],['b',element(b)]]), finish = vi.fn();batch.update(element(root),nodes,['a','b'],phases([['a','steady'],['b','steady']]),true,finish);b.y = 180;batch.measure(element(root),nodes);a.y = 100;b.y = 0;batch.update(element(root),nodes,['b','a'],phases([['a','steady'],['b','steady']]),false,finish);expect(b.writes).toContain('transform:translate(0px, 180px)');batch.dispose();expect(vi.getTimerCount()).toBe(0);
  });
});
