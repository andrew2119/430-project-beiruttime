import { createReadScope, type ReadScope } from './scope';
let held:ReadScope|null = null;
let input:ReadScope['input'] = 'none';
/** The root remembers modality even while a frozen route is on screen. */
export function rememberPageInput(next:'keyboard'|'pointer') {input = next;if (held) held.input = next;}
/** One in-memory adoption cache survives excursions to frozen pages. Nothing
 * is persisted and no provider/default changes for those pages. */
export function pageReadMemory(key:string):ReadScope {
  if (typeof window === 'undefined') return createReadScope(key);
  if (held?.key !== key || !held.valid()) {held?.clear();held = createReadScope(key);}
  held.input = input;
  return held;
}
export function clearPageReadMemory() {held?.clear();held = null;}
