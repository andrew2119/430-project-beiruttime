import type { ReactElement, ReactNode } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({slots: [] as unknown[], index: 0,
  proof: {data: {watch_id:'test-watch',revision:1},isError:false,error:null},
  history: {data: {items:[{revision:1,state:'approved',reason:'Private reason'}],total:1,page_size:25},isError:false,error:null as unknown},
}));
vi.mock('react', async original => ({...await original<typeof import('react')>(),
  useEffect: () => {},
  useState: (initial: unknown) => { const index=state.index++; if (!(index in state.slots)) state.slots[index]=initial;
    return [state.slots[index], (next: unknown) => {state.slots[index]=typeof next==='function'?next(state.slots[index]):next;}]; },
}));
vi.mock('./reads', () => ({useBusinessRead: ({queryKey}: {queryKey:string[]}) => queryKey[1]==='possession' ? state.proof : state.history}));
vi.mock('@/shell/access-context', () => ({useAccessContext: () => ({fingerprint:'test-access'})}));
vi.mock('@/shell/locale-context', () => ({useLocale: () => 'en'}));
import { ApiError } from '@/lib/api/client';
import { ListingPossession, ProofControls } from './possession';
function elements(node: ReactNode): ReactElement<Record<string,unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!node || typeof node!=='object' || !('props' in node)) return [];
  const element=node as ReactElement<Record<string,unknown>>;
  return [element,...elements(element.props.children as ReactNode)];
}
const render=()=>{state.index=0;return elements(ListingPossession());};
beforeEach(()=>{state.slots=[];state.history.isError=false;state.history.error=null;});
it.each([401,403])('clears proof and history on history denial %i, retaining denial through timeout', status=>{
  render(); state.slots[0]={watch:'test-watch',revision:1};
  expect(render().some(node=>node.type===ProofControls)).toBe(true);
  state.history.isError=true;state.history.error=new ApiError(status,'denied','');
  expect(render().some(node=>node.type===ProofControls)).toBe(false);
  state.history.error=new TypeError('Unavailable');
  expect(render().some(node=>node.type===ProofControls)).toBe(false);
  expect(render().some(node=>node.props.children==='Private reason')).toBe(false);
});
it.each([401,403])('clears proof and history after an evidence denial %i', status=>{
  render();state.slots[0]={watch:'test-watch',revision:1};
  const controls=render().find(node=>node.type===ProofControls)!;
  (controls.props.onDenied as (error:unknown)=>void)(new ApiError(status,'denied',''));
  expect(render().some(node=>node.type===ProofControls)).toBe(false);
  expect(render().some(node=>node.props.children==='Private reason')).toBe(false);
});
