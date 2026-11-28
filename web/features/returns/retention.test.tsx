import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
const hooks=vi.hoisted(()=>({values:[] as unknown[],cursor:0,locale:'en',effects:[] as (()=>unknown)[]}));
vi.mock('react',async(importOriginal)=>{
  const original=await importOriginal<typeof import('react')>();
  return {...original,useState:(initial:unknown)=>{const i=hooks.cursor++;if(!(i in hooks.values))hooks.values[i]=initial;return [hooks.values[i],(next:unknown)=>{hooks.values[i]=next;}];},useRef:(initial:unknown)=>{const i=hooks.cursor++;if(!(i in hooks.values))hooks.values[i]={current:initial};return hooks.values[i];},useEffect:(effect:()=>unknown)=>{hooks.effects.push(effect);}};
});
vi.mock('@/shell/locale-context',()=>({useLocale:()=>hooks.locale}));
import Returns, { type ReturnAnswer, type ReturnProvider, type ReturnCommand } from './returns';
function elements(node:unknown):ReactElement<Record<string,unknown>>[]{
  if(!node||typeof node!=='object')return [];
  const element=node as ReactElement<Record<string,unknown>>;
  const children=element.props?.children;
  return [element,...(Array.isArray(children)?children:[children]).flatMap(elements)];
}
function render(provider:ReturnProvider){hooks.cursor=0;return elements(Returns({provider}));}
function field(nodes:ReturnType<typeof render>,label:string){return nodes.find(n=>n.props?.label===label)!;}
beforeEach(()=>{hooks.values=[];hooks.cursor=0;hooks.locale='en';hooks.effects=[];});
describe('same mounted return form',()=>{
  it('retains mixed text, action, receipt and exact pending reference through locale changes',async()=>{
    let reject:(error:Error)=>void=()=>{};
    const request=vi.fn<(command:ReturnCommand,signal:AbortSignal)=>Promise<ReturnAnswer>>(()=>new Promise<ReturnAnswer>((_,fail)=>{reject=fail;}));
    const provider={request,current:vi.fn()};
    let nodes=render(provider);
    (field(nodes,'Order reference').props.onValueChange as (s:string)=>void)('order-ساعة⌚');
    (field(nodes,'Return reason').props.onValueChange as (s:string)=>void)('Long العربية Latin ⌚');
    (field(nodes,'Action').props.onValueChange as (s:string)=>void)('receive');
    nodes=render(provider);
    (field(nodes,'Actual custody receipt reference').props.onValueChange as (s:string)=>void)('receipt-1');
    nodes=render(provider);
    const submission=(nodes.find(n=>n.type==='form')!.props.onSubmit as (e:{preventDefault:()=>void})=>Promise<void>)({preventDefault(){}});
    hooks.locale='ar';nodes=render(provider);
    expect(field(nodes,'مرجع الطلب').props.value).toBe('order-ساعة⌚');
    expect(field(nodes,'سبب الإرجاع').props.value).toBe('Long العربية Latin ⌚');
    expect(field(nodes,'الإجراء').props.value).toBe('receive');
    expect(field(nodes,'مرجع إيصال الحيازة الفعلي').props.value).toBe('receipt-1');
    expect(request).toHaveBeenCalledTimes(1);
    const first=request.mock.calls[0];
    reject(new Error('lost response'));await submission;
    nodes=render(provider);
    const retry=(nodes.find(n=>n.type==='form')!.props.onSubmit as (e:{preventDefault:()=>void})=>Promise<void>)({preventDefault(){}});
    expect(request.mock.calls[1][0]).toBe(first[0]);
    reject(new Error('lost response'));await retry;
  });
});


describe('order response binding',()=>{
  function refresh(nodes:ReturnType<typeof render>){
    return (nodes.find(n=>n.props?.children==='Refresh current state')!.props.onClick as ()=>Promise<void>)();
  }
  it('clears the previous status and uses revision zero for a different order',async()=>{
    const request=vi.fn<(command:ReturnCommand,signal:AbortSignal)=>Promise<ReturnAnswer>>(async command=>({operation_id:command.operation_id,subject_id:command.subject_id,state:'requested',revision:1}));
    const provider={request,current:vi.fn(async()=>({operation_id:'prior',subject_id:'first',state:'permitted' as const,revision:7}))};
    let nodes=render(provider);
    (field(nodes,'Order reference').props.onValueChange as (s:string)=>void)('first');
    await refresh(render(provider));
    nodes=render(provider);
    expect(nodes.some(n=>n.props?.title==='Return permitted')).toBe(true);
    (field(nodes,'Order reference').props.onValueChange as (s:string)=>void)('second');
    nodes=render(provider);
    expect(nodes.some(n=>n.props?.title==='Return permitted')).toBe(false);
    (field(nodes,'Return reason').props.onValueChange as (s:string)=>void)('Review');
    nodes=render(provider);
    await (nodes.find(n=>n.type==='form')!.props.onSubmit as (e:{preventDefault:()=>void})=>Promise<void>)({preventDefault(){}});
    expect(request.mock.calls[0][0]).toMatchObject({subject_id:'second',expected_revision:0});
  });
  it('rejects a current response for another order',async()=>{
    const provider={request:vi.fn(),current:vi.fn(async()=>({operation_id:'prior',subject_id:'other',state:'refunded' as const,revision:8}))};
    let nodes=render(provider);
    (field(nodes,'Order reference').props.onValueChange as (s:string)=>void)('first');
    await refresh(render(provider));
    nodes=render(provider);
    expect(nodes.some(n=>n.props?.title==='Simulated refund confirmed')).toBe(false);
    expect(nodes.some(n=>n.props?.title==='Returns unavailable')).toBe(true);
  });
  it('keeps a mismatched command response pending for the same operation retry',async()=>{
    const request=vi.fn<(command:ReturnCommand,signal:AbortSignal)=>Promise<ReturnAnswer>>(async command=>({operation_id:command.operation_id,subject_id:'other',state:'refunded',revision:8}));
    const provider={request,current:vi.fn()};
    let nodes=render(provider);
    (field(nodes,'Order reference').props.onValueChange as (s:string)=>void)('first');
    (field(nodes,'Return reason').props.onValueChange as (s:string)=>void)('Review');
    async function submit(){nodes=render(provider);await (nodes.find(n=>n.type==='form')!.props.onSubmit as (e:{preventDefault:()=>void})=>Promise<void>)({preventDefault(){}});}
    await submit();nodes=render(provider);
    expect(nodes.some(n=>n.props?.title==='Simulated refund confirmed')).toBe(false);
    expect(nodes.some(n=>n.props?.title==='Result pending')).toBe(true);
    await submit();expect(request.mock.calls[1][0]).toBe(request.mock.calls[0][0]);
  });
});
