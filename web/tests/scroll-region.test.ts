import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { KeyboardEvent } from 'react';
import { scrollRegionKey } from '../../packages/ui/src/foundation/scroll-keys';
class Box {
  dataset:Record<string,string> = {axis:'vertical'};scrollTop = 0;scrollLeft = 0;scrollHeight = 500;clientHeight = 100;scrollWidth = 300;clientWidth = 100;direction = 'ltr';
  scrollTo = vi.fn(({top,left}:{top:number;left:number})=>{this.scrollTop = top;this.scrollLeft = left;});
}
function press(box:Box,key:string,extra:Record<string,unknown> = {}) {const preventDefault = vi.fn();scrollRegionKey({key,currentTarget:box,target:box,preventDefault,...extra} as unknown as KeyboardEvent<HTMLElement>);return preventDefault;}
beforeEach(()=>vi.stubGlobal('getComputedStyle',(box:Box)=>({direction:box.direction})));
afterEach(()=>vi.unstubAllGlobals());
describe('portable self-focused region keyboard scrolling',()=>{
  it('handles each vertical direction/page/home/end only when actual movement remains',()=>{
    const box = new Box();for (const key of ['ArrowUp','PageUp','Home']) expect(press(box,key)).not.toHaveBeenCalled();
    expect(press(box,'ArrowDown')).toHaveBeenCalledOnce();expect(box.scrollTop).toBe(80);press(box,'PageDown');expect(box.scrollTop).toBe(170);press(box,'ArrowUp');expect(box.scrollTop).toBe(90);press(box,'PageUp');expect(box.scrollTop).toBe(0);press(box,'End');expect(box.scrollTop).toBe(400);
    for (const key of ['ArrowDown','PageDown','End']) expect(press(box,key)).not.toHaveBeenCalled();press(box,'Home');expect(box.scrollTop).toBe(0);expect(box.scrollTo).toHaveBeenLastCalledWith({top:0,left:0,behavior:'instant'});
  });
  it('leaves fitting content, exhausted edges, descendants and modified/default-handled keys to their owner',()=>{
    const box = new Box();box.scrollHeight = box.clientHeight;for (const key of ['ArrowDown','ArrowUp','PageDown','PageUp','Home','End','ArrowRight']) expect(press(box,key)).not.toHaveBeenCalled();box.scrollHeight = 500;
    for (const modifier of ['altKey','ctrlKey','metaKey','shiftKey','defaultPrevented']) expect(press(box,'ArrowDown',{[modifier]:true})).not.toHaveBeenCalled();for (const target of [{tagName:'INPUT'},{tagName:'BUTTON'}]) expect(press(box,'ArrowDown',{target})).not.toHaveBeenCalled();expect(press(box,'Tab')).not.toHaveBeenCalled();expect(box.scrollTo).not.toHaveBeenCalled();
  });
  it('moves supported horizontal axes physically in LTR/RTL and leaves both edges untrapped',()=>{
    for (const direction of ['ltr','rtl']) {
      const box = new Box();box.dataset.axis = 'horizontal';box.direction = direction;const forward = direction === 'rtl' ? 'ArrowLeft' : 'ArrowRight', back = direction === 'rtl' ? 'ArrowRight' : 'ArrowLeft', sign = direction === 'rtl' ? -1 : 1;
      expect(press(box,back)).not.toHaveBeenCalled();press(box,forward);expect(box.scrollLeft).toBe(sign*80);press(box,'PageDown');expect(box.scrollLeft).toBe(sign*170);press(box,'End');expect(box.scrollLeft).toBe(sign*200);expect(press(box,forward)).not.toHaveBeenCalled();press(box,'PageUp');expect(box.scrollLeft).toBe(sign*110);press(box,'Home');expect(box.scrollLeft).toBe(0);expect(press(box,'ArrowDown')).not.toHaveBeenCalled();
    }
  });
  it('both-axis regions handle independent extents without borrowing keys from their child controls',()=>{
    const box = new Box();box.dataset.axis = 'both';press(box,'ArrowRight');press(box,'ArrowDown');expect(box.scrollLeft).toBe(80);expect(box.scrollTop).toBe(80);expect(press(box,'ArrowLeft',{target:{tagName:'INPUT'}})).not.toHaveBeenCalled();press(box,'End');expect(box.scrollTop).toBe(400);expect(box.scrollLeft).toBe(80);
  });
});
