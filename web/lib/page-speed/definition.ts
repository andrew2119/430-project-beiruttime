import type { Query, QueryKey } from '@tanstack/react-query';
import { ANSWER_FRESH_MS, ANSWER_HELD_MS } from './policy';
import type { ReadScope } from './scope';
export type PageRead<T> = Readonly<{key:QueryKey;ask:(signal:AbortSignal)=>Promise<T>;warm:'safe'|'open-only';fresh:number}>;
/** Intent and the mounted view share exactly one question, key and call. */
export function definePageRead<A extends unknown[],T>(spec:{key:(...args:A)=>QueryKey;ask:(signal:AbortSignal,...args:A)=>Promise<T>;warm:'safe'|'open-only';fresh?:number}) {
  const fresh = spec.fresh ?? ANSWER_FRESH_MS, {key:question,ask,warm} = spec;
  if (!Number.isFinite(fresh) || fresh < 0 || fresh > ANSWER_FRESH_MS || !['safe','open-only'].includes(warm)) throw new Error('Invalid page read policy');
  return (...args:A):PageRead<T>=>{const key = question(...args);if (!Array.isArray(key) || !key.length || typeof key[0] !== 'string' || !key[0]) throw new Error('A page read needs a stable question key');return Object.freeze({key:Object.freeze([...key]),ask:(signal:AbortSignal)=>ask(signal,...args),warm,fresh});};
}
export function optionsFor<T>(scope:ReadScope,read:PageRead<T>) {
  return {queryKey:['bt-page',scope.key,...read.key],queryFn:async({signal}:{signal:AbortSignal})=>{
    if (!scope.valid() || signal.aborted) throw new Error('Page access changed');
    const answer = await read.ask(signal);
    if (!scope.valid() || signal.aborted) throw new Error('Page access changed');
    return answer;
  },staleTime:read.fresh,gcTime:ANSWER_HELD_MS,retry:false as const};
}
export function keptPageAnswer<T>(scope:ReadScope,answer:T|undefined,previous:Pick<Query,'queryKey'|'queryHash'>|undefined):T|undefined {
  return scope.valid() && previous?.queryKey[1] === scope.key && scope.client.getQueryCache().get(previous.queryHash) === previous ? answer : undefined;
}
export function warmPageRead<T>(scope:ReadScope,read:PageRead<T>):Promise<void> {
  if (!scope.valid() || read.warm !== 'safe') return Promise.resolve();
  return scope.client.prefetchQuery(optionsFor(scope,read));
}
