import { Children, isValidElement, type ReactElement } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
import { Button, Input } from '@beirut-time/ui/foundation';
import type { RefundCommand } from '@contracts/contracts-orders/refunds';
import type { RefundPort, RefundRead } from './model';

const state=vi.hoisted(()=>({slots:[] as unknown[],cursor:0,locale:'en' as 'en'|'ar',
  data:undefined as RefundRead|undefined,error:null as unknown}));
const refetch=vi.hoisted(()=>vi.fn());
vi.mock('react',async()=>({...await vi.importActual('react'),
  useSyncExternalStore:(_subscribe:unknown,get:()=>unknown)=>get(),
  useState:(initial:unknown)=>{
    const at=state.cursor++;
    if (!(at in state.slots)) state.slots[at]=typeof initial==='function' ? initial() : initial;
    return [state.slots[at],(next:unknown)=>{state.slots[at]=typeof next==='function' ? next(state.slots[at]) : next;}];
  }}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/features/identity/session',()=>({useSession:()=>({access_fingerprint:'scope'})}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:state.data,error:state.error,
  isPending:false,isFetching:false,refetch})}));
import RefundView from './view';
import { copy } from './copy';

type View=ReactElement<Record<string,unknown>>;
function elements(value:unknown):View[] {
  if (!isValidElement(value)) return [];
  const node=value as View;
  return [node,...Children.toArray(node.props.children as never).flatMap(elements)];
}
function draw(port:RefundPort) {
  state.cursor=0;
  const form=elements(RefundView({port})).find(node=>node.props.port===port)!;
  return (form.type as (props:Record<string,unknown>)=>View)(form.props);
}
function button(port:RefundPort,label:string) {
  return elements(draw(port)).find(node=>node.type===Button && node.props.children===label)!;
}
const binding={subject_id:'order',watch_id:'watch',actor_id:'operator',organization_id:'business',
  expected_revision:1,source_revision:1,quote_id:'quote',quote_revision:1,policy_revision:1,basis_id:'basis'};
beforeEach(()=>{state.slots=[];state.cursor=0;state.error=null;
  state.data={binding,remaining_minor:500000};refetch.mockReset();});

it.each(['en','ar'] as const)('reloads a failed basis read and reconciles the exact pending refund in %s',async locale=>{
  state.locale=locale;const t=copy[locale];
  const pending=(command:RefundCommand)=>({...command,state:'pending' as const,revision:2,
    pending_reason:'processing' as const,next_actor:'payout_operator' as const,
    next_review_at:'2026-11-18T00:00:00Z',simulated:true as const});
  const request=vi.fn(async(command:RefundCommand)=>pending(command));
  const lookup=vi.fn(async(command:RefundCommand)=>pending(command));
  const port:RefundPort={current:vi.fn(),request,lookup};
  refetch.mockImplementationOnce(async()=>{
    state.error=new Error('unavailable');return {data:state.data,error:state.error};
  }).mockImplementation(async()=>{
    state.error=null;state.data={binding:{...binding,expected_revision:2},remaining_minor:487450};
    return {data:state.data,error:null};
  });
  const input=elements(draw(port)).find(node=>node.type===Input)!;
  (input.props.onValueChange as (value:string)=>void)('١٢٥٫٥٠');
  const form=elements(draw(port)).find(node=>node.type==='form')!;
  (form.props.onSubmit as (event:unknown)=>void)({preventDefault:vi.fn()});
  await vi.waitFor(()=>{
    expect(state.error).toBeInstanceOf(Error);
    expect(button(port,t.lookup).props.disabled).toBe(true);
  });
  expect(request).toHaveBeenCalledOnce();
  const original=request.mock.calls[0][0];
  expect(original.amount_minor).toBe(12550);
  expect(button(port,t.retry).props.disabled).toBe(true);
  expect(button(port,t.load).props.disabled).toBe(false);
  const reload=button(port,t.load).props.onClick as ()=>void;
  reload();
  await vi.waitFor(()=>expect(button(port,t.lookup).props.disabled).toBe(false));
  expect(elements(draw(port)).find(node=>node.type===Input)?.props.value).toBe('١٢٥٫٥٠');
  expect(elements(draw(port)).some(node=>node.type==='bdi' && node.props.children===original.operation_id)).toBe(true);
  await (button(port,t.lookup).props.onClick as ()=>Promise<void>)();
  expect(lookup).toHaveBeenCalledOnce();
  expect(lookup.mock.calls[0][0]).toBe(original);
  expect(request).toHaveBeenCalledOnce();
  expect(refetch).toHaveBeenCalledTimes(3);
});
