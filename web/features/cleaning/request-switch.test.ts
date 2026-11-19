import type { ReactElement } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
const hooks=vi.hoisted(()=>({values:[] as unknown[],cursor:0}));
vi.mock('react',async original=>({
  ...await original<typeof import('react')>(),
  useState:(initial:unknown)=>{
    const index=hooks.cursor++;
    if(!(index in hooks.values)) hooks.values[index]=initial;
    return [hooks.values[index],(value:unknown)=>{hooks.values[index]=value;}];
  },
  useRef:(initial:unknown)=>{
    const index=hooks.cursor++;
    if(!(index in hooks.values)) hooks.values[index]={current:initial};
    return hooks.values[index];
  },
}));
vi.mock('next/navigation',()=>({useSearchParams:()=>new URLSearchParams('request=00000000-0000-4000-8000-000000000002')}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=> 'en'}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:'current'})}));
vi.mock('@/features/identity/session',()=>({useSession:()=>null,authenticatedRequest:vi.fn()}));
import Cleaning from './view';
type Node=ReactElement<Record<string, unknown>>;
function renderScope() {
  hooks.cursor=0;
  const scope=Cleaning() as unknown as ReactElement<{access:string}>;
  const tree=(scope.type as (props:{access:string})=>Node)(scope.props);
  const body=(tree.props.children as Node[])[1];
  const [form,request]=body.props.children as Node[];
  const [input,button]=form.props.children as Node[];
  return {scope,form,request,input,button};
}
beforeEach(()=>{hooks.values=[];hooks.cursor=0;});
it('keeps the same mounted request and recovery callback while switching is locked',()=>{
  let screen=renderScope();
  const original=screen.request.key;
  const lock=screen.request.props.lockSwitch as (value:boolean)=>void;
  const change=screen.input.props.onValueChange as (value:string)=>void;
  const open=screen.form.props.onSubmit as (event:{preventDefault:()=>void})=>void;
  lock(true);
  change('00000000-0000-4000-8000-000000000099');
  // A previously captured submit handler also observes the synchronous lock.
  open({preventDefault:vi.fn()});
  screen=renderScope();
  (screen.form.props.onSubmit as typeof open)({preventDefault:vi.fn()});
  screen=renderScope();
  expect(screen.request.key).toBe(original);
  expect(screen.input.props.disabled).toBe(true);
  expect(screen.button.props.disabled).toBe(true);
  expect(screen.scope.key).toBe('current');
  lock(false);
  screen=renderScope();
  (screen.form.props.onSubmit as typeof open)({preventDefault:vi.fn()});
  screen=renderScope();
  expect(screen.request.key).toBe('00000000-0000-4000-8000-000000000099');
  expect(screen.button.props.disabled).toBe(false);
});
