import { afterEach, describe, expect, it, vi } from 'vitest';
import { QueryObserver } from '@tanstack/react-query';
import { createReadScope } from '@/lib/page-speed/scope';
import { optionsFor, warmPageRead } from '@/lib/page-speed/definition';
import { passportRead } from './reads';
import fixture from '../../../packages/contracts-trust/passports/fixtures.json';

const scopes: ReturnType<typeof createReadScope>[] = [];
function scope() {
  const value = createReadScope('public');
  scopes.push(value);
  return value;
}
afterEach(()=>{
  scopes.splice(0).forEach(value=>value.clear());
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});
const id = fixture.signed.summary.passport_id;
const answer = {state:'verified',document:fixture.signed};
describe('passport shared answer lifetime',()=>{
  it('adopts the identical warmed read on opening and revisit without a placeholder or second request',async()=>{
    const current = scope(), fetch = vi.fn(async()=>Response.json(answer));
    vi.stubGlobal('fetch',fetch);
    await warmPageRead(current,passportRead(id));
    for (let visit=0;visit<2;visit++) {
      const observer = new QueryObserver(current.client,optionsFor(current,passportRead(id)));
      const leave = observer.subscribe(()=>{});
      expect(observer.getCurrentResult().data).toEqual(answer);
      expect(observer.getCurrentResult().isPending).toBe(false);
      leave();
      observer.destroy();
    }
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('keeps the signed answer during a failed refresh and separates references and access',async()=>{
    const current = scope();
    vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(Response.json(answer)).mockRejectedValueOnce(new Error('timeout')));
    await warmPageRead(current,passportRead(id));
    const observer = new QueryObserver(current.client,optionsFor(current,passportRead(id)));
    const leave = observer.subscribe(()=>{});
    const retry = observer.refetch();
    expect(observer.getCurrentResult().data).toEqual(answer);
    await retry;
    expect(observer.getCurrentResult().isError).toBe(true);
    expect(observer.getCurrentResult().data).toEqual(answer);
    expect(current.client.getQueryData(optionsFor(current,passportRead('00000000-0000-0000-0000-000000000099')).queryKey)).toBeUndefined();
    leave();
    observer.destroy();
    current.clear();
    expect(scope().client.getQueryData(optionsFor(current,passportRead(id)).queryKey)).toBeUndefined();
  });
});


describe('passport cancellation compatibility',()=>{
  function withoutCombinedSignals() {
    vi.stubGlobal('AbortSignal', new Proxy(AbortSignal,{get(target,key,receiver) {
      return key === 'any' ? undefined : Reflect.get(target,key,receiver);
    }}));
  }
  it('verifies the same reference without combined or timeout signal APIs',async()=>{
    withoutCombinedSignals();
    vi.spyOn(AbortSignal,'timeout').mockImplementation(()=>{throw new Error('Unsupported');});
    const fetch = vi.fn(async()=>Response.json(answer));
    vi.stubGlobal('fetch',fetch);
    expect(await passportRead(id).ask(new AbortController().signal)).toEqual(answer);
    expect(fetch).toHaveBeenCalledWith(`/passports/${id}/read`,expect.objectContaining({signal:expect.any(AbortSignal)}));
  });
  it.each(['timeout','cancel','already cancelled'] as const)('bounds fallback reads on %s',async mode=>{
    withoutCombinedSignals();
    vi.useFakeTimers();
    const parent = new AbortController();
    if (mode === 'already cancelled') parent.abort();
    const fetch = vi.fn((_url,options:{signal:AbortSignal})=>new Promise<Response>((_resolve,reject)=>{
      if (options.signal.aborted) reject(new Error('Cancelled'));
      else options.signal.addEventListener('abort',()=>reject(new Error('Cancelled')),{once:true});
    }));
    vi.stubGlobal('fetch',fetch);
    const pending = expect(passportRead(id).ask(parent.signal)).rejects.toThrow('Verification unavailable');
    if (mode === 'timeout') await vi.advanceTimersByTimeAsync(4000);
    else if (mode === 'cancel') parent.abort();
    await pending;
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });
});
