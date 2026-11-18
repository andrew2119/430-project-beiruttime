import { afterEach, describe, expect, it, vi } from 'vitest';
import { QueryObserver } from '@tanstack/react-query';
import { createReadScope, type ReadScope } from '../lib/page-speed/scope';
import { clearPageReadMemory, pageReadMemory, rememberPageInput } from '../lib/page-speed/memory';
import { definePageRead, keptPageAnswer, optionsFor, warmPageRead } from '../lib/page-speed/definition';
import { ANSWER_FRESH_MS, ANSWER_HELD_MS } from '../lib/page-speed/policy';
import { delayedPending } from '../lib/page-speed/delay';
import { replacePageQuery } from '../lib/page-speed/address';
import { demoRequest, demoRead } from '../internal/page/reads';
import { demoAnswer } from '../internal/page/demo-data';
import { GET } from '../app/api/internal/page-data/route';
import { NextRequest } from 'next/server';
import { fitVisualViewport } from '../shell/foundation/viewport';
const scopes:ReadScope[] = [];
const scope = (key='member:a')=>{const value = createReadScope(key);scopes.push(value);return value;};
function deferred<T>() {let resolve!:(value:T)=>void;const promise = new Promise<T>(done=>{resolve=done;});return {promise,resolve};}
afterEach(()=>{for (const value of scopes.splice(0)) value.clear();clearPageReadMemory();vi.useRealTimers();vi.unstubAllGlobals();vi.restoreAllMocks();});
describe('the actual shared read/cache contract, not a network timing proof',()=>{
  it('intent and page share one key/call; a fresh warm costs no second read',async()=>{
    const current = scope(), pending = deferred<number>(), ask = vi.fn(()=>pending.promise), question = definePageRead({key:(id:string)=>['example',id],ask,warm:'safe'});
    const warming = warmPageRead(current,question('one')), opening = current.client.fetchQuery(optionsFor(current,question('one')));expect(ask).toHaveBeenCalledOnce();pending.resolve(7);await warming;expect(await opening).toBe(7);
    expect(await current.client.fetchQuery(optionsFor(current,question('one')))).toBe(7);expect(ask).toHaveBeenCalledOnce();expect(question('one').fresh).toBe(ANSWER_FRESH_MS);expect(current.client.getQueryDefaults([])).toEqual({});expect(optionsFor(current,question('one')).gcTime).toBe(ANSWER_HELD_MS);
  });
  it('a real QueryObserver retains content while stale data refreshes and on a failed refresh',async()=>{
    const current = scope(), next = deferred<number>(), ask = vi.fn().mockResolvedValueOnce(3).mockImplementationOnce(()=>next.promise).mockRejectedValueOnce(new Error('offline'));
    const question = definePageRead({key:()=>['refresh'],ask,warm:'safe',fresh:0})();await current.client.fetchQuery(optionsFor(current,question));
    const observer = new QueryObserver(current.client,optionsFor(current,question)), release = observer.subscribe(()=>{});
    expect(observer.getCurrentResult().data).toBe(3);expect(observer.getCurrentResult().isPending).toBe(false);expect(observer.getCurrentResult().isFetching).toBe(true);
    next.resolve(4);await vi.waitFor(()=>expect(observer.getCurrentResult().data).toBe(4));await observer.refetch();expect(observer.getCurrentResult().data).toBe(4);expect(observer.getCurrentResult().isError).toBe(true);expect(observer.getCurrentResult().isPending).toBe(false);release();observer.destroy();
  });
  it('changed filters keep only the exact still-held previous query in the current scope',async()=>{
    const current = scope(), question = definePageRead({key:()=>['filter'],ask:async()=>0,warm:'safe'})();await warmPageRead(current,question);
    const previous = current.client.getQueryCache().find({queryKey:optionsFor(current,question).queryKey})!;
    expect(keptPageAnswer(current,0,previous)).toBe(0);expect(keptPageAnswer(scope('member:b'),0,previous)).toBeUndefined();current.client.removeQueries({queryKey:previous.queryKey});expect(keptPageAnswer(current,0,previous)).toBeUndefined();
  });
  it('access clear cancels late work even if its fetch ignores abort; next identity sees no old answer',async()=>{
    const first = scope(), late = deferred<string>(), question = definePageRead({key:()=>['private'],ask:()=>late.promise,warm:'safe'})();const opening = first.client.fetchQuery(optionsFor(first,question)).catch(()=>null);
    first.clear();late.resolve('old');await opening;expect(first.client.getQueryCache().getAll()).toHaveLength(0);expect(first.valid()).toBe(false);const next = scope('member:b');expect(next.client.getQueryData(optionsFor(next,question).queryKey)).toBeUndefined();
    expect(()=>first.claimArrival('screen')).not.toThrow();expect(first.claimArrival('screen')).toBe(false);
  });
  it('the actual query function fences a late answer even without a QueryClient cancellation listener',async()=>{
    const current=scope(), late=deferred<string>(), question=definePageRead({key:()=>['late-direct'],ask:()=>late.promise,warm:'safe'})(), pending=optionsFor(current,question).queryFn({signal:new AbortController().signal});current.clear();late.resolve('old answer');await expect(pending).rejects.toThrow('Page access changed');
  });
  it('memory survives a route excursion but never a scope change or explicit access purge',()=>{
    vi.stubGlobal('window',{});const first = pageReadMemory('a');first.client.setQueryData(['example'],1);expect(pageReadMemory('a')).toBe(first);expect(pageReadMemory('a').client.getQueryData(['example'])).toBe(1);
    const next = pageReadMemory('b');expect(first.valid()).toBe(false);expect(next.client.getQueryCache().getAll()).toHaveLength(0);clearPageReadMemory();expect(next.valid()).toBe(false);expect(pageReadMemory('b')).not.toBe(next);
  });
  it('keyboard intent on a frozen route reaches the next adopted first answer without a fade',()=>{
    vi.stubGlobal('window',{});rememberPageInput('pointer');const first = pageReadMemory('a');rememberPageInput('keyboard');expect(pageReadMemory('a')).toBe(first);expect(first.claimArrival('not-yet-shown')).toBe(false);clearPageReadMemory();expect(pageReadMemory('b').input).toBe('keyboard');rememberPageInput('pointer');
  });
  it('open-only questions never warm, malformed policies fail closed and arrival never replays',async()=>{
    const current = scope(), ask = vi.fn(async()=>1), question = definePageRead({key:()=>['audited'],ask,warm:'open-only'})();await warmPageRead(current,question);expect(ask).not.toHaveBeenCalled();expect(await current.client.fetchQuery(optionsFor(current,question))).toBe(1);
    for (const fresh of [Infinity,-1,NaN,ANSWER_FRESH_MS+1]) expect(()=>definePageRead({key:()=>['bad'],ask,warm:'safe',fresh})).toThrow();expect(()=>definePageRead({key:()=>[],ask,warm:'safe'})()).toThrow();
    const specification = {key:()=>['fixed-policy'],ask,warm:'open-only' as 'safe'|'open-only'}, fixed = definePageRead(specification);specification.warm='safe';expect(fixed().warm).toBe('open-only');expect(Object.isFrozen(fixed())).toBe(true);expect(Object.isFrozen(fixed().key)).toBe(true);
    expect(current.claimArrival('page')).toBe(true);expect(current.claimArrival('page')).toBe(false);current.input = 'keyboard';expect(current.claimArrival('other')).toBe(false);current.input = 'pointer';expect(current.claimArrival('other')).toBe(false);
  });
});
describe('real local review endpoint and bounded parser, no domain write/read',()=>{
  it('walks every one of a thousand records, and drives zero/one/worst bodies through the same endpoint',async()=>{
    const ids = new Set<string>();for (let page=0;page<84;page++) {const response = GET(new NextRequest(`https://example.test/api/internal/page-data?data=thousand&page=${page}`));expect(response.headers.get('cache-control')).toBe('no-store');const data = await response.json();expect(data.total).toBe(1000);expect(data.pages).toBe(84);expect(data.items.length).toBe(page === 83 ? 4 : 12);for (const item of data.items) ids.add(item.id);}expect(ids.size).toBe(1000);
    for (const [mode,total] of [['empty',0],['one',1],['worst',13]] as const) {const data = demoAnswer(demoRequest(mode,'0'),1);expect(data.total).toBe(total);expect(data.items.length).toBe(Math.min(12,total));}
    expect(demoRequest('invalid','-1')).toEqual({mode:'demo',page:0});expect(demoRequest('thousand','999')).toEqual({mode:'thousand',page:83});expect(demoAnswer(demoRequest('one','83'),1).page).toBe(0);
  });
  it('the page read calls only the example endpoint with abort and refuses an invalid answer',async()=>{
    const deadline = new AbortController(), timeout = vi.spyOn(AbortSignal,'timeout').mockReturnValue(deadline.signal), fetch = vi.fn(async(path:RequestInfo|URL,options?:RequestInit)=>{void path;void options;return {ok:true,json:async()=>demoAnswer({mode:'one',page:0},1)};});vi.stubGlobal('fetch',fetch);const controller = new AbortController();expect((await demoRead({mode:'one',page:0}).ask(controller.signal)).total).toBe(1);expect(fetch).toHaveBeenCalledWith('/api/internal/page-data?data=one&page=0',expect.objectContaining({cache:'no-store',credentials:'same-origin'}));expect(timeout).toHaveBeenCalledWith(4000);expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(false);controller.abort();expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);
    fetch.mockResolvedValueOnce({ok:true,json:async()=>({items:[],total:Infinity})} as never);await expect(demoRead({mode:'one',page:0}).ask(controller.signal)).rejects.toThrow('Invalid');
  });
});
describe('pending/visual-viewport controllers with a bounded clock and geometry',()=>{
  it('warm commit cancels pending before its threshold, including a stale queued callback',()=>{
    vi.useFakeTimers();const show = vi.fn(), stop = delayedPending(120,show);vi.advanceTimersByTime(119);expect(show).not.toHaveBeenCalled();stop();vi.advanceTimersByTime(100);expect(show).not.toHaveBeenCalled();
    let queued!:()=>void;const late = delayedPending(120,show,run=>{queued=run;return 1;},()=>{});late();queued();expect(show).not.toHaveBeenCalled();const slow = delayedPending(120,show);vi.advanceTimersByTime(120);expect(show).toHaveBeenCalledOnce();slow();
  });
  it('data filters and the existing preview share a same-document update without dropping other URL parts',()=>{
    const replaceState=vi.fn();vi.stubGlobal('window',{location:{href:'https://example.test/ar/internal/page?keep=one&page=4#note'},history:{replaceState}});const url=replacePageQuery({data:'worst',page:'0'});expect(url.pathname).toBe('/ar/internal/page');expect(url.searchParams.get('keep')).toBe('one');expect(url.searchParams.get('data')).toBe('worst');expect(url.hash).toBe('#note');expect(replaceState).toHaveBeenCalledWith(null,'',url);
  });
  it('caps only its frame, follows keyboard height, preserves zoom and restores listeners/style',()=>{
    const viewport = Object.assign(new EventTarget(),{height:700,scale:1}), view = Object.assign(new EventTarget(),{visualViewport:viewport,innerHeight:800}), element = {style:{maxBlockSize:'90rem'}};
    const stop = fitVisualViewport(element as HTMLElement,view as unknown as Window);expect(element.style.maxBlockSize).toBe('700px');viewport.height = 390;viewport.dispatchEvent(new Event('resize'));expect(element.style.maxBlockSize).toBe('390px');viewport.scale = 2;viewport.dispatchEvent(new Event('resize'));expect(element.style.maxBlockSize).toBe('90rem');viewport.scale = 1;viewport.height = NaN;view.dispatchEvent(new Event('resize'));expect(element.style.maxBlockSize).toBe('90rem');stop();viewport.height = 300;viewport.dispatchEvent(new Event('resize'));expect(element.style.maxBlockSize).toBe('90rem');
  });
});
