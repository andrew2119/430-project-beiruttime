import { afterEach, describe, expect, it, vi } from 'vitest';
import { createDragLoader, touchCapable } from '../../packages/ui/src/foundation/drag-loader';
import type { attachDragDismiss, DragParts } from '../../packages/ui/src/foundation/drag-engine';
const parts:DragParts = {shade:()=>null,dismiss:()=>{},allowed:()=>true};
const node = {} as HTMLElement;
const settle = async()=>{await Promise.resolve();await Promise.resolve();};
afterEach(()=>vi.unstubAllGlobals());
describe('touch implementation is genuinely demand loaded',()=>{
  it('makes no read on a mouse-only attachment and recognizes touch/coarse capability',()=>{
    const read = vi.fn(), attach = createDragLoader(read);attach(node,parts,false)();expect(read).not.toHaveBeenCalled();
    vi.stubGlobal('window',{matchMedia:()=>({matches:false})});vi.stubGlobal('navigator',{maxTouchPoints:0});expect(touchCapable()).toBe(false);vi.stubGlobal('navigator',{maxTouchPoints:1});expect(touchCapable()).toBe(true);vi.stubGlobal('navigator',{maxTouchPoints:0});vi.stubGlobal('window',{matchMedia:()=>({matches:true})});expect(touchCapable()).toBe(true);
  });
  it('shares one pending read, skips a removed surface and detaches the surviving owner once',async()=>{
    let resolve!:(value:{attachDragDismiss:typeof attachDragDismiss})=>void;const detach = vi.fn(), engine = vi.fn(()=>detach), read = vi.fn(()=>new Promise<{attachDragDismiss:typeof attachDragDismiss}>(done=>{resolve = done;})), attach = createDragLoader(read);
    const first = attach(node,parts,true), second = attach(node,parts,true);expect(read).toHaveBeenCalledOnce();first();resolve({attachDragDismiss:engine});await settle();expect(engine).toHaveBeenCalledExactlyOnceWith(node,parts);second();second();expect(detach).toHaveBeenCalledOnce();
  });
  it('a failed optional engine never blocks normal controls and a later attachment retries',async()=>{
    const engine = vi.fn(()=>vi.fn()), read = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({attachDragDismiss:engine}), attach = createDragLoader(read);
    attach(node,parts,true)();await settle();const release = attach(node,parts,true);await settle();expect(read).toHaveBeenCalledTimes(2);expect(engine).toHaveBeenCalledOnce();release();
  });
});
