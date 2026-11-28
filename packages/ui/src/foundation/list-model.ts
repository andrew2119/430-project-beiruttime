export type ListKey = string|number;
export type RowPhase = 'steady'|'enter'|'exit'|'resume';
export type ListSnapshot<T> = {source:readonly T[]; order:ListKey[]; items:Map<ListKey,T>; phases:Map<ListKey,RowPhase>; seen:Set<ListKey>; revision:number; atomic:boolean};
function keyed<T>(items:readonly T[],key:(item:T)=>ListKey):Map<ListKey,T> {
  const result = new Map<ListKey,T>();
  for (const item of items) {const id = key(item);if (result.has(id) || (typeof id === 'number' && !Number.isFinite(id))) throw new Error('Live list keys must be unique and finite.');result.set(id,item);}
  return result;
}
export function initialList<T>(source:readonly T[],key:(item:T)=>ListKey):ListSnapshot<T> {
  const items = keyed(source,key);return {source,order:[...items.keys()],items,phases:new Map([...items.keys()].map(id=>[id,'steady'])),seen:new Set(items.keys()),revision:0,atomic:true};
}
export function updateList<T>(previous:ListSnapshot<T>,source:readonly T[],key:(item:T)=>ListKey,enters:((item:T,seen:boolean)=>boolean)|undefined,animate:boolean):ListSnapshot<T> {
  const next = keyed(source,key), survives = !next.size || [...next.keys()].some(id=>previous.items.has(id));
  const items = new Map(next), phases = new Map<ListKey,RowPhase>(), seen = new Set(previous.seen);
  for (const [id,item] of next) {
    const old = previous.phases.get(id);
    phases.set(id,!animate || !survives ? 'steady' : old === 'exit' ? 'resume' : old === 'enter' ? 'enter' : old ? 'steady' : enters?.(item,seen.has(id)) ? 'enter' : 'steady');
    seen.add(id);
  }
  if (animate && survives) for (const [id,item] of previous.items) if (!next.has(id)) {items.set(id,item);phases.set(id,'exit');}
  const order:ListKey[] = [], emitted = new Set<ListKey>(), nextOrder = [...next.keys()];let cursor = 0;
  const through = (stop:ListKey|null) => {while (cursor < nextOrder.length) {const id = nextOrder[cursor++];if (!emitted.has(id)) {order.push(id);emitted.add(id);}if (id === stop) break;}};
  for (const id of previous.order) {if (emitted.has(id)) continue;if (!next.has(id)) {if (items.has(id)) {order.push(id);emitted.add(id);}} else through(id);}
  through(null);
  return {source,order,items,phases,seen,revision:previous.revision+1,atomic:!animate || !survives};
}
export function finishListExit<T>(snapshot:ListSnapshot<T>,key:ListKey):ListSnapshot<T> {
  if (snapshot.phases.get(key) !== 'exit') return snapshot;
  const items = new Map(snapshot.items), phases = new Map(snapshot.phases);items.delete(key);phases.delete(key);
  return {...snapshot,items,phases,order:snapshot.order.filter(id=>id !== key),revision:snapshot.revision+1};
}
