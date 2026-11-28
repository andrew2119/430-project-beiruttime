'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { cn } from '../utils';
import { prefersReducedMotion } from '../motion-tokens';
import { finishListExit, initialList, updateList, type ListKey, type RowPhase } from './list-model';
import { createRowBatch } from './row-motion';
type Batch = ReturnType<typeof createRowBatch>;
type Props<T> = {items:readonly T[]; getKey:(item:T)=>ListKey; children:(item:T,index:number)=>ReactNode; enters?:(item:T,shownBefore:boolean)=>boolean; empty?:ReactNode; grid?:boolean; className?:string; input?:'pointer'|'keyboard'|'none'};

function Row({itemKey,phase,children,nodesRef,batchRef}: {itemKey:ListKey; phase:RowPhase; children:ReactNode; nodesRef:RefObject<Map<ListKey,HTMLElement>>; batchRef:RefObject<Batch>}) {
  const attach = useCallback((node:HTMLDivElement|null)=>{
    if (!node) return;
    nodesRef.current.set(itemKey,node);
    return ()=>{if (nodesRef.current.get(itemKey) === node) {nodesRef.current.delete(itemKey);batchRef.current.remove(itemKey);}};
  },[itemKey,nodesRef,batchRef]);
  return <div ref={attach} role="listitem" className="bt-row-motion" inert={phase === 'exit' ? true : undefined} aria-hidden={phase === 'exit' ? true : undefined}>{children}</div>;
}
function ListCore<T>({items,getKey,children,enters,empty,grid = false,className,input = 'none'}:Props<T>) {
  const [snapshot,setSnapshot] = useState(()=>initialList(items,getKey));
  const immediate = input === 'keyboard' || prefersReducedMotion();
  if (snapshot.source !== items) setSnapshot(updateList(snapshot,items,getKey,enters,!immediate));
  const rootRef = useRef<HTMLDivElement|null>(null), nodesRef = useRef(new Map<ListKey,HTMLElement>()), batchRef = useRef(createRowBatch());
  const finish = useCallback((key:ListKey)=>setSnapshot(current=>finishListExit(current,key)),[]);
  useLayoutEffect(()=>{
    if (rootRef.current) batchRef.current.update(rootRef.current,nodesRef.current,snapshot.order,snapshot.phases,snapshot.atomic || immediate,finish);
  },[snapshot,immediate,finish,children,grid,className]);
  useEffect(()=>{
    const root = rootRef.current, batch = batchRef.current;
    if (!root || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(()=>batch.measure(root,nodesRef.current));observer.observe(root);
    return ()=>observer.disconnect();
  },[]);
  useEffect(()=>{const batch = batchRef.current;return ()=>batch.dispose();},[]);
  return <div ref={rootRef} role={snapshot.order.length ? 'list' : undefined} className={cn('bt-live-list',grid && 'bt-row-grid',className)} data-bt-motion-input={input}>
    {snapshot.order.length ? snapshot.order.map((key,index)=><Row key={key} itemKey={key} phase={snapshot.phases.get(key) ?? 'steady'} nodesRef={nodesRef} batchRef={batchRef}>{children(snapshot.items.get(key) as T,index)}</Row>) : empty}
  </div>;
}
/** Scope changes clear retained rows in the same commit, never through an exit
 * hold. A signed-in caller uses its access partition as the required scope. */
export function AnimatedList<T>({scopeKey,items,getKey,children,enters,empty,grid,className,input}:Props<T> & {scopeKey:string}) {
  return <ListCore key={scopeKey} items={items} getKey={getKey} enters={enters} empty={empty} grid={grid} className={className} input={input}>{children}</ListCore>;
}
