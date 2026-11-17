import { beforeEach, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { createReadScope } from '@/lib/page-speed/scope';
import { optionsFor } from '@/lib/page-speed/definition';
import { sellerApplicationRead } from './reads';
let scope:ReturnType<typeof createReadScope>;
const state=vi.hoisted(()=>({slots:[] as unknown[],cursor:0,invoke:vi.fn(),refetch:vi.fn(),effects:[] as (()=>unknown)[]}));
vi.mock('react',async()=>({...(await vi.importActual('react')),
  useEffect:(effect:()=>unknown)=>{state.effects.push(effect);},useCallback:(value:unknown)=>value,
  useState:(initial:unknown)=>{const index=state.cursor++;if(!(index in state.slots))state.slots[index]=initial;return [state.slots[index],(value:unknown)=>{state.slots[index]=value;}];},
  useRef:(initial:unknown)=>{const index=state.cursor++;if(!(index in state.slots))state.slots[index]={current:initial};return state.slots[index];}}));
vi.mock('./session',()=>({authenticatedRequest:state.invoke,useSession:()=>({access_fingerprint:'test-access'})}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:scope.client.getQueryData(optionsFor(scope,sellerApplicationRead('test-access')).queryKey) ?? {application:null},error:null,refetch:state.refetch})}));
vi.mock('@/lib/page-speed/arrival',()=>({AnswerArrival:({children}:{children:unknown})=>children}));
vi.mock('./shared',()=>({useIdentityCopy:()=>({locale:'en',t:new Proxy({},{get:(_target,key)=>String(key)})}),ErrorNotice:()=>null,SessionPrompt:()=>null,syntheticFile:async()=> 'DEMO: test proof'}));
import SellerView from './seller-view';
import { PossessionForm } from './possession-view';
import { ApiError } from '@/lib/api/client';
type Node=ReactElement<Record<string,unknown>>;
function nodes(value:unknown):Node[]{if(Array.isArray(value))return value.flatMap(nodes);if(!value||typeof value!=='object'||!('props' in value))return [];const node=value as Node;return [node,...nodes(node.props.children)];}
function possession(){state.cursor=0;return nodes(PossessionForm({fingerprint:'test-access'}));}
async function click(tree:Node[],label:string){await (tree.find(node=>node.props.children===label)!.props.onClick as ()=>Promise<void>)();}
beforeEach(()=>{scope=createReadScope('test-access');state.refetch.mockReset().mockResolvedValue({error:null});state.slots=[];state.cursor=0;state.effects=[];state.invoke.mockReset();vi.stubGlobal('requestAnimationFrame',()=>0);});
it('keeps an unresolved possession command through rate limits and unrelated read errors',async()=>{
  state.invoke.mockResolvedValueOnce({proof:null}).mockRejectedValueOnce(new Error('response lost'))
    .mockRejectedValueOnce(new ApiError(429,'try_later','')).mockRejectedValueOnce(new ApiError(422,'invalid_proof','')).mockResolvedValueOnce({proof:null});
  const tree=possession();(tree.find(node=>'onValueChange' in node.props)!.props.onValueChange as (value:string)=>void)('test-listing');
  await click(possession(),'readProof');await click(possession(),'issueProof');
  const original=state.invoke.mock.calls[1];
  await click(possession(),'retry');await click(possession(),'readProof');await click(possession(),'retry');
  expect(state.invoke.mock.calls[2]).toEqual(original);expect(state.invoke.mock.calls[4]).toEqual(original);
  expect(possession().some(node=>node.props.children==='retry')).toBe(false);
});
it('retries a seller submission with its original body and reference after rate limiting',async()=>{
  const child=nodes(SellerView()).find(node=>typeof node.type==='function'&&node.props.fingerprint==='test-access')!;
  const render=()=>{state.cursor=0;return nodes((child.type as (props:typeof child.props)=>ReactElement)(child.props));};
  render();
  vi.stubGlobal('FormData',class {get(name:string){return `test-${name}`;}});
  state.invoke.mockRejectedValueOnce(new Error('response lost')).mockRejectedValueOnce(new ApiError(429,'try_later','')).mockResolvedValueOnce({application:{status:'pending'}});
  const submit=async()=>{const form=render().find(node=>'onSubmit' in node.props)!;await (form.props.onSubmit as (event:unknown)=>Promise<void>)({preventDefault(){},currentTarget:{reset:vi.fn()}});};
  await submit();const original=state.invoke.mock.calls[0];await submit();await submit();
  expect(state.invoke.mock.calls[1]).toEqual(original);expect(state.invoke.mock.calls[2]).toEqual(original);
});

it.each([null,'correction','rejected'])('keeps acknowledged pending submission when refresh fails after %s',async previous=>{
  const key=optionsFor(scope,sellerApplicationRead('test-access')).queryKey;
  scope.client.setQueryData(key,{application:previous?{id:'test-case',status:previous,revision:1}:null});
  const child=nodes(SellerView()).find(node=>typeof node.type==='function'&&node.props.fingerprint==='test-access')!;
  const render=()=>{state.cursor=0;return nodes((child.type as (props:typeof child.props)=>ReactElement)(child.props));};
  vi.stubGlobal('FormData',class {get(name:string){return `test-${name}`;}});
  const result={application:{id:'test-case',status:'pending',revision:2}};
  state.invoke.mockResolvedValueOnce(result);
  state.refetch.mockImplementationOnce(async()=>{
    return {error:new ApiError(503,'unavailable','')};
  });
  const reset=vi.fn();
  await (render().find(node=>'onSubmit' in node.props)!.props.onSubmit as (event:unknown)=>Promise<void>)({preventDefault(){},currentTarget:{reset}});
  expect(reset).toHaveBeenCalledOnce();
  expect(render().some(node=>node.props['data-state']==='pending')).toBe(true);
  expect(render().some(node=>'onSubmit' in node.props)).toBe(false);
  expect(state.invoke).toHaveBeenCalledOnce();
});
