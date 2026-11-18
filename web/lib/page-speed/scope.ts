import { QueryClient } from '@tanstack/react-query';
import { ANSWER_FRESH_MS, ANSWER_HELD_MS } from './policy';

export function createReadScope(key: string) {
  let active = true;
  const shown = new Set<string>();
  const client = new QueryClient({defaultOptions:{queries:{staleTime:ANSWER_FRESH_MS,gcTime:ANSWER_HELD_MS,retry:false,refetchOnWindowFocus:false}}});
  const scope = {key,client,input:'none' as 'none'|'keyboard'|'pointer',valid:()=>active,
    claimArrival(view:string) {if (!active || shown.has(view)) return false;shown.add(view);return scope.input !== 'keyboard';},
    clear() {active = false;shown.clear();void client.cancelQueries().catch(()=>{});client.clear();},
  };
  return scope;
}
export type ReadScope = ReturnType<typeof createReadScope>;
