import { afterEach, describe, expect, it, vi } from 'vitest';
import { initialList, updateList, finishListExit } from '../../packages/ui/src/foundation/list-model';
import { filterSelectOptions, matchingChoice } from '../../packages/ui/src/foundation/select-model';
import { createSelectRuntime } from '../../packages/ui/src/foundation/select-runtime';
import { decodeFrame, type FrameAnswer } from '../../packages/ui/src/foundation/image-decode';
import { formatAmount, formatCount } from '@beirut-time/ui/foundation';
import { currentToasts, clearToasts, closeToast, finishToast, mountToastOutlet, pauseToast, setToastVisibility, subscribeToasts, toast } from '../../packages/ui/src/foundation/toast-store';
import { COPY } from '../internal/components/copy';
import { DATA_MODES, boardData, pageOf, reviewLocale, reviewMode } from '../internal/components/model';
const key = (item:{id:string})=>item.id;
const first = {id:'a'}, second = {id:'b'}, added = {id:'c'};
afterEach(()=>{clearToasts();setToastVisibility(false);vi.useRealTimers();vi.unstubAllGlobals();});
describe('live keyed data ownership',()=>{
  it('paints initial data steadily and rejects ambiguous keys',()=>{
    const list = initialList([first,second],key);expect([...list.phases.values()]).toEqual(['steady','steady']);
    expect(()=>initialList([first,first],key)).toThrow(/unique/);expect(()=>initialList([NaN],value=>value)).toThrow(/finite/);
  });
  it('retains a removing entrance once and reverses an undo without restarting entry',()=>{
    const initial = initialList([first,second],key), arrived = updateList(initial,[first,second,added],key,()=>true,true);
    expect(arrived.phases.get('c')).toBe('enter');
    const leaving = updateList(arrived,[first,second],key,()=>true,true);expect(leaving.phases.get('c')).toBe('exit');expect(leaving.order).toEqual(['a','b','c']);
    const undone = updateList(leaving,[first,second,added],key,()=>true,true);expect(undone.phases.get('c')).toBe('resume');
    expect(finishListExit(undone,'c')).toBe(undone);expect(finishListExit(leaving,'c').order).toEqual(['a','b']);
  });
  it('holds gaps only until exit and preserves order across reorder/empty',()=>{
    const list = initialList([first,second,added],key), leaving = updateList(list,[added,first],key,()=>true,true);
    expect(leaving.order.filter(id=>id !== 'b')).toEqual(['c','a']);expect(leaving.phases.get('b')).toBe('exit');
    const empty = updateList(list,[],key,()=>true,true);expect(empty.order).toHaveLength(3);expect([...empty.phases.values()]).toEqual(['exit','exit','exit']);
  });
  it('new scopes, keyboard changes and disjoint data replacements never retain old records',()=>{
    const list = initialList([first,second],key);
    expect(updateList(list,[added],key,()=>true,true).atomic).toBe(true);
    const keyboard = updateList(list,[first,added],key,()=>true,false);expect(keyboard.order).toEqual(['a','c']);expect([...keyboard.phases.values()]).toEqual(['steady','steady']);
    expect(initialList([added],key).items.has('a')).toBe(false);
  });
  it('requires explicit live eligibility and remembers previously shown keys',()=>{
    const list = initialList([first],key);expect(updateList(list,[first,added],key,undefined,true).phases.get('c')).toBe('steady');
    const departed = finishListExit(updateList(list,[],key,()=>true,true),'a');
    const seen = vi.fn(()=>false);updateList(departed,[first,added],key,seen,true);
    // A disjoint replacement stays atomic, even if a key has been seen.
    expect(seen).not.toHaveBeenCalled();
  });
});
describe('intent-only select implementation and model',()=>{
  it('does not read until intent; deduplicates pending work and has a stable server frame',async()=>{
    let resolve!:(value:{SelectOptions:()=>null})=>void;const read = vi.fn(()=>new Promise<{SelectOptions:()=>null}>(done=>{resolve = done;}));
    const runtime = createSelectRuntime(read), changed = vi.fn(), stop = runtime.subscribe(changed);
    expect(read).not.toHaveBeenCalled();expect(runtime.current().status).toBe('idle');const server = runtime.server();
    const firstLoad = runtime.load(), secondLoad = runtime.load();expect(firstLoad).toBe(secondLoad);expect(read).toHaveBeenCalledOnce();expect(runtime.current().status).toBe('loading');
    const Component = ()=>null;resolve({SelectOptions:Component});await firstLoad;expect(runtime.current()).toEqual({component:Component,status:'ready'});expect(runtime.server()).toBe(server);expect(server.status).toBe('idle');
    await runtime.load();expect(read).toHaveBeenCalledOnce();expect(changed).toHaveBeenCalledTimes(2);stop();
  });
  it('resolves failed warming quietly and retries a later intent',async()=>{
    const Component = ()=>null, read = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({SelectOptions:Component});
    const runtime = createSelectRuntime(read);await expect(runtime.load()).resolves.toBeUndefined();expect(runtime.current().status).toBe('error');await runtime.load();expect(read).toHaveBeenCalledTimes(2);expect(runtime.current().component).toBe(Component);
  });
  it('uses locale-aware real filtering, normalization, wrap and disabled-skipping typeahead',()=>{
    const options = [{value:'a',label:'Alpha'},{value:'b',label:'Another',disabled:true},{value:'c',label:'أوميغا'},{value:'d',label:'ＡＬＰＩＮＥ'}];
    expect(filterSelectOptions(options,'alp','en').map(item=>item.value)).toEqual(['a','d']);expect(filterSelectOptions(options,'أو','ar').map(item=>item.value)).toEqual(['c']);expect(filterSelectOptions(options,'missing','en')).toEqual([]);
    expect(matchingChoice(options,'a',0,'en')).toBe(3);expect(matchingChoice(options,'a',3,'en')).toBe(0);expect(matchingChoice(options,'z',0,'en')).toBe(-1);
  });
});
describe('decoded pixels belong to the current image element',()=>{
  it('holds the placeholder through decode and marks a cached answer atomic',async()=>{
    let done!:()=>void;const image = {naturalWidth:100,decode:()=>new Promise<void>(resolve=>{done = resolve;})} as HTMLImageElement;
    const settle = vi.fn(), work = decodeFrame(image,'/watch.webp',true,()=>true,settle);expect(settle).not.toHaveBeenCalled();done();await work;expect(settle).toHaveBeenCalledWith({src:'/watch.webp',state:'ready',instant:true});
  });
  it('ignores stale decoded pixels after a source change or unmount',async()=>{
    let done!:()=>void, current = true;const image = {naturalWidth:100,decode:()=>new Promise<void>(resolve=>{done = resolve;})} as HTMLImageElement, answers:FrameAnswer[] = [];
    const work = decodeFrame(image,'/old.webp',false,()=>current,answer=>answers.push(answer));current = false;done();await work;expect(answers).toEqual([]);
  });
  it('keeps fallback on failure and a zero-sized decoded answer',async()=>{
    const settle = vi.fn();await decodeFrame({naturalWidth:0,decode:()=>Promise.resolve()} as HTMLImageElement,'/zero.webp',false,()=>true,settle);await decodeFrame({decode:()=>Promise.reject(new Error('bad'))} as HTMLImageElement,'/bad.webp',false,()=>true,settle);
    expect(settle.mock.calls).toEqual([[{src:'/zero.webp',state:'error'}],[{src:'/bad.webp',state:'error'}]]);
  });
});
describe('canonical notification queue lifecycle',()=>{
  it('owns only one outlet and clears privacy data on release',()=>{
    vi.useFakeTimers();const release = mountToastOutlet();expect(()=>mountToastOutlet()).toThrow(/only once/);toast.info('private');release();release();expect(currentToasts()).toEqual([]);expect(vi.getTimerCount()).toBe(0);
  });
  it('shares snapshots, not records, and only removes a matching revision',()=>{
    vi.useFakeTimers();const release = mountToastOutlet(), changed = vi.fn(), stop = subscribeToasts(changed);
    const action = {label:'Keep',run:()=>false}, id = toast.loading('Pending',{id:'request',action});const old = currentToasts()[0];action.label = 'Changed';expect(old.action?.label).toBe('Keep');
    toast.success('Ready',{id});finishToast(id,old.revision);expect(currentToasts()[0].title).toBe('Ready');closeToast(id,false,old.revision);expect(currentToasts()[0].phase).toBe('open');
    closeToast(id);expect(currentToasts()[0].phase).toBe('closed');finishToast(id,currentToasts()[0].revision);expect(currentToasts()).toEqual([]);expect(changed).toHaveBeenCalledTimes(4);stop();release();
  });
  it('pauses lifetime for combined hover/focus/hidden ownership without losing remaining time',()=>{
    vi.useFakeTimers();vi.setSystemTime(0);const release = mountToastOutlet(), id = toast.info('Read',{durationMs:1000});vi.advanceTimersByTime(400);pauseToast(id,'hover',true);pauseToast(id,'focus',true);vi.advanceTimersByTime(5000);pauseToast(id,'hover',false);vi.advanceTimersByTime(5000);expect(currentToasts()[0].phase).toBe('open');pauseToast(id,'focus',false);vi.advanceTimersByTime(300);setToastVisibility(true);vi.advanceTimersByTime(5000);setToastVisibility(false);vi.advanceTimersByTime(299);expect(currentToasts()[0].phase).toBe('open');vi.advanceTimersByTime(1);expect(currentToasts()[0].phase).toBe('closed');release();
  });
  it('pending lifetimes are stable; reduced/keyboard dismiss and unmounted dismiss are atomic',()=>{
    vi.useFakeTimers();vi.stubGlobal('window',{matchMedia:()=>({matches:true})});const release = mountToastOutlet(), id = toast.loading('Pending');vi.advanceTimersByTime(100000);expect(currentToasts()).toHaveLength(1);closeToast(id);expect(currentToasts()).toEqual([]);toast.info('Keyboard',{id:'key'});closeToast('key',true);expect(currentToasts()).toEqual([]);release();toast.info('Unmounted',{id:'none'});closeToast('none');expect(currentToasts()).toEqual([]);
  });
  it('refreshes an identical still-open implicit no-action notice, with a new revision and no duplicate',()=>{
    vi.useFakeTimers();const release = mountToastOutlet(), first = toast.error('Unavailable',{description:'Try again'}), revision = currentToasts()[0].revision;
    expect(toast.error('Unavailable',{description:'Try again'})).toBe(first);expect(toast.error('Unavailable',{description:'Try again'})).toBe(first);expect(currentToasts()).toHaveLength(1);expect(currentToasts()[0].revision).toBeGreaterThan(revision);finishToast(first,revision);expect(currentToasts()).toHaveLength(1);release();
  });
  it('keeps kind/title/description differences, actions and explicit update streams independent',()=>{
    vi.useFakeTimers();const release = mountToastOutlet();toast.error('Unavailable',{description:'Try again'});toast.warning('Unavailable',{description:'Try again'});toast.error('Other',{description:'Try again'});toast.error('Unavailable',{description:'Other'});expect(currentToasts()).toHaveLength(4);
    const action = {label:'Undo',run:()=>{}};const a = toast.error('Unavailable',{description:'Try again',action}), b = toast.error('Unavailable',{description:'Try again',action});expect(a).not.toBe(b);expect(currentToasts()).toHaveLength(6);
    toast.error('Unavailable',{id:'owned',description:'Try again'});toast.error('Unavailable',{description:'Try again'});expect(currentToasts()).toHaveLength(7);toast.success('Done',{id:'owned'});expect(currentToasts().find(entry=>entry.id === 'owned')?.kind).toBe('success');release();
  });
  it('never reuses a closed repeat identity and stale close cannot remove its new notice',()=>{
    vi.useFakeTimers();const release = mountToastOutlet(), old = toast.error('Unavailable'), revision = currentToasts()[0].revision;closeToast(old);const next = toast.error('Unavailable');expect(next).not.toBe(old);expect(currentToasts()).toHaveLength(2);finishToast(old,revision);expect(currentToasts().map(entry=>entry.id)).toEqual([next]);release();
  });
  it('restarts readability time on refresh and retains active pause/hidden ownership',()=>{
    vi.useFakeTimers();vi.setSystemTime(0);const release = mountToastOutlet(), id = toast.error('Unavailable',{durationMs:1000});vi.advanceTimersByTime(800);toast.error('Unavailable',{durationMs:1000});vi.advanceTimersByTime(999);expect(currentToasts()[0].phase).toBe('open');vi.advanceTimersByTime(1);expect(currentToasts()[0].phase).toBe('closed');finishToast(id,currentToasts()[0].revision);
    const paused = toast.error('Unavailable',{durationMs:1000});pauseToast(paused,'hover',true);setToastVisibility(true);toast.error('Unavailable',{durationMs:1000});vi.advanceTimersByTime(5000);setToastVisibility(false);vi.advanceTimersByTime(5000);expect(currentToasts()[0].phase).toBe('open');pauseToast(paused,'hover',false);vi.advanceTimersByTime(999);expect(currentToasts()[0].phase).toBe('open');vi.advanceTimersByTime(1);expect(currentToasts()[0].phase).toBe('closed');release();
  });
  it('an invalid repeat update does not cancel the existing notice lifetime',()=>{
    vi.useFakeTimers();const release = mountToastOutlet();toast.error('Unavailable',{durationMs:1000});expect(()=>toast.error('Unavailable',{durationMs:NaN})).toThrow(RangeError);vi.advanceTimersByTime(1000);expect(currentToasts()[0].phase).toBe('closed');release();
  });
  it('rejects invalid lifetimes instead of leaving an unbounded invisible task',()=>{expect(()=>toast.info('Invalid',{durationMs:NaN})).toThrow(RangeError);expect(()=>toast.info('Invalid',{durationMs:-1})).toThrow(RangeError);});
});
describe('exact numbers and complete local drawing-board pagination',()=>{
  it('formats decimal strings without floating point rounding and validates missing/unsafe values',()=>{
    expect(formatAmount('9000000000000000.99','en','USD','Missing')).toBe('9,000,000,000,000,000.99 USD');expect(formatAmount('0.01','en','USD','Missing')).toBe('0.01 USD');expect(formatAmount('0.001','en','USD','Missing')).toBe('Missing');expect(formatAmount(null,'ar','USD','غير متاح')).toBe('غير متاح');
    expect(formatCount(NaN,'en',COPY.en.counts,'Missing')).toBe('Missing');expect(formatCount(Number.MAX_SAFE_INTEGER+1,'en',COPY.en.counts,'Missing')).toBe('Missing');expect(formatCount(0,'en',COPY.en.counts,'Missing')).toBe('0 watches');expect(formatCount(2,'ar',COPY.ar.counts,'Missing')).toBe('ساعتان');expect(formatAmount('1234.90','ar','USD','Missing')).toContain('١٬٢٣٤٫٩٠');
  });
  it('offers every stable data mode and reaches all 1000 independent records in bounded pages',()=>{
    expect(DATA_MODES).toEqual(['demo','worst','empty','one','thousand']);expect(reviewMode('invalid')).toBe('demo');expect(reviewLocale(['ar'],'ar')).toBe('ar');expect(reviewLocale('en','ar')).toBe('en');
    const items = boardData('thousand'), all = Array.from({length:pageOf(items,0).pages},(_,page)=>pageOf(items,page).items).flat();expect(all).toHaveLength(1000);expect(new Set(all.map(item=>item.id)).size).toBe(1000);expect(pageOf(items,999).items).toHaveLength(4);expect(pageOf(items,NaN).page).toBe(0);expect(pageOf([],2)).toEqual({items:[],total:0,page:0,pages:1});expect(boardData('one')).toHaveLength(1);expect(boardData('empty')).toHaveLength(0);
  });
});
