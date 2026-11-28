import type { ComponentType } from 'react';
import type { SelectImplementationProps } from './select-types';
type Runtime = {component:ComponentType<SelectImplementationProps>|null; status:'idle'|'loading'|'ready'|'error'};
type OptionsModule = {SelectOptions:ComponentType<SelectImplementationProps>};
/** One in-flight intent load; an unsuccessful warm may be retried. */
export function createSelectRuntime(read:()=>Promise<OptionsModule>) {
  const initial:Runtime = {component:null,status:'idle'}, listeners = new Set<()=>void>();
  let current = initial, loading:Promise<void>|undefined;
  const publish = (next:Runtime) => {current = next;for (const listener of listeners) listener();};
  const load = ():Promise<void> => {
    if (current.component) return Promise.resolve();
    if (!loading) {
      publish({component:null,status:'loading'});
      loading = read().then(module=>{publish({component:module.SelectOptions,status:'ready'});},()=>{loading = undefined;publish({component:null,status:'error'});});
    }
    return loading;
  };
  return {current:()=>current,server:()=>initial,subscribe:(listener:()=>void)=>{listeners.add(listener);return ()=>listeners.delete(listener);},load};
}
// The popup module has no eager import edge from the closed control.
export const defaultSelectRuntime = createSelectRuntime(()=>import('./select-options'));
/** A delivery gate can defer/fail readiness, never substitute another control.
 * The only successful implementation remains the same shared options module. */
export const gatedSelectRuntime = (gate:()=>Promise<void>)=>createSelectRuntime(async()=>{await gate();return import('./select-options');});
export const selectRuntime = defaultSelectRuntime.current, serverSelectRuntime = defaultSelectRuntime.server, subscribeSelect = defaultSelectRuntime.subscribe, loadSelect = defaultSelectRuntime.load;
