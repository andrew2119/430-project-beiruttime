import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createReadScope, type ReadScope } from '../lib/page-speed/scope';
import { createPageWarmer, startPageWarming, warmingAddress, type PageRouter } from '../lib/page-speed/engine';
import { pageFor } from '../lib/page-speed/pages';
import { PAGE_REQUEST_HELD_MS, POINTER_REST_MS, VISIBLE_CHECK_MS, IDLE_FALLBACK_MS } from '../lib/page-speed/policy';
const answers = vi.hoisted(()=>vi.fn(async()=>{}));
vi.mock('../lib/page-speed/pages',async()=>({...await vi.importActual('../lib/page-speed/pages'),warmPageAnswers:answers}));
class LinkPart extends EventTarget {
  isConnected = true; glance = true; attrs = new Map<string,string>();
  constructor(href:string) {super();this.attrs.set('href',href);}
  getAttribute(name:string) {return this.attrs.get(name) ?? null;} hasAttribute(name:string) {return this.attrs.has(name);}
  closest(selector:string) {return selector === '[data-bt-glance]' ? this.glance ? this : null : selector === 'a[href]' ? this : null;}
  contains(node:unknown) {return node === this;}
}
class Doc extends EventTarget {
  hidden = false; location = {origin:'https://example.test',pathname:'/en/internal/page',search:''}; documentElement = {}; activeElement:LinkPart|null = null; links:LinkPart[] = [];
  querySelectorAll(selector:string) {return selector === ':hover' ? [] : this.links;}
}
let intersection:(entries:{isIntersecting:boolean;target:LinkPart}[])=>void, mutation:(records:unknown[])=>void;
let scope:ReadScope, stopped:(()=>void)[];
beforeEach(()=>{
  vi.useFakeTimers();scope = createReadScope('review:a');stopped = [];answers.mockClear();
  vi.stubGlobal('Element',LinkPart);vi.stubGlobal('Node',LinkPart);
  vi.stubGlobal('IntersectionObserver',class {constructor(run:typeof intersection) {intersection=run;}observe=vi.fn();unobserve=vi.fn();disconnect=vi.fn();});
  vi.stubGlobal('MutationObserver',class {constructor(run:typeof mutation) {mutation=run;}observe=vi.fn();disconnect=vi.fn();});
  vi.stubGlobal('requestIdleCallback',(run:()=>void)=>setTimeout(run,1));vi.stubGlobal('cancelIdleCallback',clearTimeout);
});
afterEach(()=>{stopped.forEach(stop=>stop());scope.clear();vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals();});
function event(doc:Doc,type:string,target:LinkPart,values:Record<string,unknown>={}) {const event = new Event(type);Object.defineProperties(event,Object.fromEntries(Object.entries({target,pointerType:'mouse',button:0,...values}).map(([key,value])=>[key,{value}])));doc.dispatchEvent(event);}
const element = (part:LinkPart)=>part as unknown as Element;
describe('full-page dispatch and adoption fences, not emitted-chunk or press-time proof',()=>{
  it('recognizes only exact reviewed routes, rejects external/download/new-tab/action/financial paths',()=>{
    for (const path of ['/checkout','/buyer/auctions/id','/api/internal/page-data','/internal/unknown','//other.test/internal/page','https://other.test/internal/page','/internal/page#section']) expect(pageFor(path)).toBeNull();
    expect(pageFor('/ar/internal/components')).not.toBeNull();expect(pageFor('/en/internal/page?data=one')).not.toBeNull();
    const link = new LinkPart('/en/internal/page');expect(warmingAddress(element(link),'https://example.test')).toBe('/en/internal/page');link.attrs.set('target','_blank');expect(warmingAddress(element(link),'https://example.test')).toBeNull();link.attrs.delete('target');link.attrs.set('aria-disabled','true');expect(warmingAddress(element(link),'https://example.test')).toBeNull();link.attrs.delete('aria-disabled');link.attrs.set('download','');expect(warmingAddress(element(link),'https://example.test')).toBeNull();
  });
  it('asks Next for full destination payload, holds requests, renews on invalidation/expiry and fences old access',()=>{
    let now = 0;const prefetch = vi.fn(), read = vi.fn(async()=>{}), warmer = createPageWarmer({prefetch},scope,()=>now,read);
    warmer.warm('/en/internal/components');expect(prefetch.mock.calls[0][1].kind).toBe('full');warmer.warm('/en/internal/components');expect(prefetch).toHaveBeenCalledOnce();expect(read).toHaveBeenCalledTimes(2);
    prefetch.mock.calls[0][1].onInvalidate();warmer.warm('/en/internal/components',false);expect(prefetch).toHaveBeenCalledTimes(2);expect(read).toHaveBeenCalledTimes(2);now += PAGE_REQUEST_HELD_MS;warmer.warm('/en/internal/components',false);expect(prefetch).toHaveBeenCalledTimes(3);prefetch.mock.calls[1][1].onInvalidate();warmer.warm('/en/internal/components',false);expect(prefetch).toHaveBeenCalledTimes(3);
    warmer.warm('/checkout');scope.clear();warmer.warm('/en/internal/page');expect(prefetch).toHaveBeenCalledTimes(3);warmer.stop();
  });
  it('actual installed listeners warm on rest/focus/touch, never a modified press, and stop cleanly',()=>{
    const doc = new Doc(), prefetch = vi.fn(), link = new LinkPart('/ar/internal/components');doc.links=[link];const engine = startPageWarming({prefetch} as PageRouter,scope,doc as unknown as Document);stopped.push(engine.stop);expect(engine.ownsGlance).toBe(true);
    event(doc,'pointerover',link);vi.advanceTimersByTime(POINTER_REST_MS-1);expect(prefetch).not.toHaveBeenCalled();event(doc,'pointerout',link,{relatedTarget:null});vi.advanceTimersByTime(1);expect(prefetch).not.toHaveBeenCalled();
    event(doc,'pointerover',link);vi.advanceTimersByTime(POINTER_REST_MS);expect(prefetch).toHaveBeenCalledOnce();expect(answers).toHaveBeenCalledOnce();event(doc,'pointerdown',link,{metaKey:true});expect(answers).toHaveBeenCalledOnce();event(doc,'focusin',link);expect(answers).toHaveBeenCalledTimes(2);event(doc,'pointerdown',link,{pointerType:'touch'});expect(answers).toHaveBeenCalledTimes(3);
    engine.stop();event(doc,'focusin',link);vi.advanceTimersByTime(100);expect(answers).toHaveBeenCalledTimes(3);
  });
  it('glances only visible attached rows in idle batches, hidden tabs stop, periodic renewal asks no destination reads',()=>{
    const doc = new Doc(), prefetch = vi.fn(), links = Array.from({length:6},(_,index)=>new LinkPart(`/en/internal/page?data=one&page=${index}`));doc.links=links;
    const engine = startPageWarming({prefetch} as PageRouter,scope,doc as unknown as Document);stopped.push(engine.stop);intersection(links.map(target=>({target,isIntersecting:true})));vi.advanceTimersByTime(1);expect(prefetch).toHaveBeenCalledTimes(4);vi.advanceTimersByTime(1);expect(prefetch).toHaveBeenCalledTimes(6);expect(answers).toHaveBeenCalledTimes(6);
    doc.hidden = true;doc.dispatchEvent(new Event('visibilitychange'));vi.advanceTimersByTime(PAGE_REQUEST_HELD_MS+VISIBLE_CHECK_MS);expect(prefetch).toHaveBeenCalledTimes(6);doc.hidden = false;doc.dispatchEvent(new Event('visibilitychange'));vi.advanceTimersByTime(2);expect(prefetch).toHaveBeenCalledTimes(12);expect(answers).toHaveBeenCalledTimes(6);
    links[0].isConnected = false;mutation([{type:'childList'}]);intersection([{target:links[1],isIntersecting:false}]);engine.look();vi.advanceTimersByTime(2);expect(answers).toHaveBeenCalledTimes(10);
  });
  it('the small idle fallback remains cancellable on engines without requestIdleCallback',()=>{
    vi.stubGlobal('requestIdleCallback',undefined);const doc=new Doc(), link=new LinkPart('/en/internal/components'), prefetch=vi.fn();doc.links=[link];const engine=startPageWarming({prefetch} as PageRouter,scope,doc as unknown as Document);stopped.push(engine.stop);intersection([{target:link,isIntersecting:true}]);vi.advanceTimersByTime(IDLE_FALLBACK_MS-1);expect(prefetch).not.toHaveBeenCalled();engine.stop();vi.advanceTimersByTime(1);expect(prefetch).not.toHaveBeenCalled();
  });
  it('a visible changed href or newly enabled row warms the new destination, not unrelated visible reads',()=>{
    const doc = new Doc(), prefetch = vi.fn(), first = new LinkPart('/en/internal/components'), other = new LinkPart('/en/internal/page?data=one');doc.links=[first,other];const engine=startPageWarming({prefetch} as PageRouter,scope,doc as unknown as Document);stopped.push(engine.stop);intersection(doc.links.map(target=>({target,isIntersecting:true})));vi.advanceTimersByTime(1);answers.mockClear();first.attrs.set('href','/en/internal/page?data=worst');mutation([{type:'attributes',attributeName:'href',target:first}]);vi.advanceTimersByTime(1);expect(answers).toHaveBeenCalledExactlyOnceWith('/en/internal/page?data=worst',scope);first.attrs.set('aria-disabled','true');mutation([{type:'attributes',attributeName:'aria-disabled',target:first}]);vi.advanceTimersByTime(1);expect(answers).toHaveBeenCalledOnce();
  });
  it('intent already present when the lazy engine arrives still warms; missing observers retain native full-prefetch ownership',()=>{
    const doc = new Doc(), link = new LinkPart('/en/internal/components'), prefetch = vi.fn();doc.activeElement=link;vi.stubGlobal('IntersectionObserver',undefined);vi.stubGlobal('MutationObserver',undefined);
    const engine = startPageWarming({prefetch} as PageRouter,scope,doc as unknown as Document);stopped.push(engine.stop);expect(prefetch).toHaveBeenCalledOnce();expect(engine.ownsGlance).toBe(false);
  });
});
