import { afterEach, describe, expect, it, vi } from 'vitest';
import { Children, isValidElement, type ReactElement } from 'react';
import { ImageFrame, type ImageFrameProps } from '../../packages/ui/src/foundation/image-frame';
const hooks = vi.hoisted(()=>({slots:[] as unknown[],cursor:0}));
vi.mock('react',async()=>{
  const real = await vi.importActual<typeof import('react')>('react');
  return {...real,useCallback:(fn:unknown)=>fn,useRef:(initial:unknown)=>{
    const at = hooks.cursor++;if (!(at in hooks.slots)) hooks.slots[at] = {current:initial};return hooks.slots[at];
  },useState:(initial:unknown)=>{
    const slots = hooks.slots, at = hooks.cursor++;if (!(at in slots)) slots[at] = typeof initial === 'function' ? initial() : initial;
    return [slots[at],(next:unknown)=>{slots[at] = typeof next === 'function' ? next(slots[at]) : next;}];
  }};
});
type Frame = ReactElement<Record<string,unknown>>;
type Pixels = ReactElement<{ref:(image:HTMLImageElement|null)=>void;onLoad:(event:{currentTarget:HTMLImageElement})=>void;onError:(event:{currentTarget:HTMLImageElement})=>void;'data-ready'?:string;'data-instant'?:string}>;
let owner:string|undefined, attached:Pixels['props']['ref']|undefined;
function frame(src:string):Frame {
  hooks.cursor = 0;
  const outer = ImageFrame({src,alt:'Watch',width:480,height:360,placeholder:'Photo'});
  if (typeof outer.type !== 'function') return outer as Frame;
  if (owner !== String(outer.key)) {attached?.(null);attached = undefined;hooks.slots = [];owner = String(outer.key);}
  hooks.cursor = 0;
  return (outer.type as (props:ImageFrameProps)=>Frame)(outer.props);
}
function pixels(view:Frame):Pixels|undefined {return Children.toArray(view.props.children as never).find(child=>isValidElement(child) && child.type === 'img') as Pixels|undefined;}
function mount(view:Frame,image:HTMLImageElement) {const part = pixels(view)!;attached = part.props.ref;attached(image);return part;}
function image(cached = false) {let finish!:()=>void;const decode = vi.fn(()=>new Promise<void>(resolve=>{finish = resolve;}));return {node:{complete:cached,naturalWidth:100,decode} as unknown as HTMLImageElement,decode,finish:()=>finish()};}
const settle = async()=>{await Promise.resolve();await Promise.resolve();};
afterEach(()=>{attached?.(null);attached = undefined;owner = undefined;hooks.slots = [];hooks.cursor = 0;});
describe('actual image render state across keyed source lifetimes (bounded hooks, not a DOM)',()=>{
  it('A decoded → pending B → new A paints loading until the new A element establishes its own answer',async()=>{
    const a = image(), first = mount(frame('/a.webp'),a.node);first.props.onLoad({currentTarget:a.node});a.finish();await settle();expect(frame('/a.webp').props['data-image-state']).toBe('ready');
    const b = image(), middle = mount(frame('/b.webp'),b.node);middle.props.onLoad({currentTarget:b.node});const returning = frame('/a.webp');expect(returning.props['data-image-state']).toBe('loading');expect(pixels(returning)?.props['data-ready']).toBeUndefined();
    b.finish();await settle();expect(frame('/a.webp').props['data-image-state']).toBe('loading');const next = image();mount(frame('/a.webp'),next.node).props.onLoad({currentTarget:next.node});next.finish();await settle();expect(frame('/a.webp').props['data-image-state']).toBe('ready');
  });
  it('failed A → B → A creates a fresh image instead of suppressing it with the old failure',()=>{
    const a = image(), part = mount(frame('/a.webp'),a.node);part.props.onError({currentTarget:a.node});expect(frame('/a.webp').props['data-image-state']).toBe('error');expect(pixels(frame('/a.webp'))).toBeUndefined();frame('/b.webp');expect(frame('/a.webp').props['data-image-state']).toBe('loading');expect(pixels(frame('/a.webp'))).toBeDefined();
  });
  it('cached ref plus load delivery decodes once and never downgrades an atomic cached answer',async()=>{
    const cached = image(true), part = mount(frame('/a.webp'),cached.node);part.props.onLoad({currentTarget:cached.node});expect(cached.decode).toHaveBeenCalledOnce();cached.finish();await settle();const ready = frame('/a.webp');expect(ready.props['data-image-state']).toBe('ready');expect(pixels(ready)?.props['data-instant']).toBe('');part.props.onLoad({currentTarget:cached.node});await settle();expect(cached.decode).toHaveBeenCalledOnce();expect(pixels(frame('/a.webp'))?.props['data-instant']).toBe('');
  });
  it('stale same-URL completion after removal/unmount never marks fresh undecoded pixels ready',async()=>{
    const old = image(), part = mount(frame('/a.webp'),old.node);part.props.onLoad({currentTarget:old.node});attached?.(null);attached = undefined;hooks.slots = [];owner = undefined;frame('/a.webp');old.finish();await settle();expect(frame('/a.webp').props['data-image-state']).toBe('loading');expect(pixels(frame('/a.webp'))?.props['data-ready']).toBeUndefined();
  });
});
