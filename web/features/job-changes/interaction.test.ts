import { isValidElement, type ReactElement } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api/client';
import en from './en.json';
import ar from './ar.json';
import fixture from '../../../packages/contracts-catalog/job-changes/fixtures.json';
const hooks=vi.hoisted(()=>({slots:[] as unknown[],index:0,locale:'en',fetching:false,send:vi.fn(),review:{} as Record<string,unknown>,error:null as ApiError|null}));
vi.mock('react',async()=>{
 const actual=await vi.importActual<typeof import('react')>('react');
 return {...actual,useEffect:(effect:()=>void)=>effect(),useState:<T,>(initial:T)=>{
  const index=hooks.index++;
  if(!(index in hooks.slots))hooks.slots[index]=initial;
  return [hooks.slots[index],(value:T)=>{hooks.slots[index]=value;}];
 },useRef:<T,>(initial:T)=>{
  const index=hooks.index++;
  if(!(index in hooks.slots))hooks.slots[index]={current:initial};
  return hooks.slots[index];
 }};
});
vi.mock('@/shell/locale-context',()=>({useLocale:()=>hooks.locale}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:'private-1'})}));
vi.mock('@/features/identity/session',()=>({authenticatedRequest:(...args:unknown[])=>hooks.send(...args)}));
vi.mock('next/navigation',()=>({useSearchParams:()=>new URLSearchParams()}));
vi.mock('@tanstack/react-query',()=>({useQuery:()=>({data:hooks.review,error:hooks.error,isFetching:hooks.fetching,refetch:vi.fn()})}));
vi.mock('@beirut-time/ui',()=>({Button:'button',ButtonLink:'a',Card:'article',State:'aside',BidiReference:'bdi',Textarea:'textarea'}));
import { Review } from './view';
function render(operation?:string){hooks.index=0;return Review({subject:'job-1',organization:'brand-1',operation});}
function nodes(value:unknown):ReactElement<Record<string,unknown>>[]{
 if(Array.isArray(value))return value.flatMap(nodes);
 if(!isValidElement<Record<string,unknown>>(value))return [];
 return [value,...nodes(value.props.children)];
}
function button(tree:unknown,label:string){return nodes(tree).find(node=>node.type==='button'&&node.props.children===label)!;}
beforeEach(()=>{hooks.index=0;hooks.slots=[];hooks.locale='en';hooks.fetching=false;hooks.send.mockReset();hooks.error=null;hooks.review={change:fixture.change,scope:{en:'Private scope',ar:'نطاق خاص'},terms:{en:'Exact terms',ar:'شروط دقيقة'},approval:null};});
it('clears private scope and draft immediately after a command denies access',async()=>{
 let tree=render();
 const input=nodes(tree).find(node=>node.type==='textarea')!;
 (input.props.onChange as (e:{target:{value:string}})=>void)({target:{value:'Private reason'}});
 tree=render();hooks.send.mockRejectedValue(new ApiError(403,'denied',''));
 await (button(tree,en.start).props.onClick as ()=>Promise<void>)();
 tree=render();expect(tree.props.body).toBe(en.denied);expect(JSON.stringify(tree)).not.toContain('Private scope');expect(hooks.slots).not.toContain('Private reason');
});
it('retains typed reason and exact uncertain command across a language change',async()=>{
 let tree=render();
 (nodes(tree).find(node=>node.type==='textarea')!.props.onChange as (e:{target:{value:string}})=>void)({target:{value:'Long عربي Latin 😀 reason'}});
 tree=render();hooks.send.mockRejectedValue(new ApiError(503,'unavailable',''));
 await (button(tree,en.start).props.onClick as ()=>Promise<void>)();
 const first=hooks.send.mock.calls[0];hooks.locale='ar';tree=render();
 expect(nodes(tree).find(node=>node.type==='textarea')!.props.value).toBe('Long عربي Latin 😀 reason');
 await (button(tree,ar.retry).props.onClick as ()=>Promise<void>)();
 expect(hooks.send.mock.calls[1]).toEqual(first);
});

it('shows unavailable for incomplete review responses',()=>{
 for(const review of [{},{change:fixture.change},{change:fixture.change,scope:{en:'Scope'},terms:{en:'Terms',ar:'شروط'},approval:null}]){
  hooks.review=review;const tree=render();
  expect(JSON.stringify(tree)).toContain(en.unavailable);
  expect(button(tree,en.start)).toBeUndefined();
 }
});
it('hides a retained command result when a later read denies access',async()=>{
 let tree=render();
 (nodes(tree).find(node=>node.type==='textarea')!.props.onChange as (e:{target:{value:string}})=>void)({target:{value:'Changed movement'}});
 tree=render();hooks.send.mockResolvedValue(fixture.responses.lost_hold_response);
 await (button(tree,en.start).props.onClick as ()=>Promise<void>)();
 expect(JSON.stringify(render())).toContain('change-1');
 for(const status of [401,403,404]){
  hooks.error=new ApiError(status,'denied','');tree=render();
  expect(tree.props.body).toBe(en.denied);expect(JSON.stringify(tree)).not.toContain('change-1');
 }
});

it('keeps the reason and review content visible during refresh in both languages',()=>{
 let tree=render();
 const reason='Long عربي Latin 😀 reason';
 (nodes(tree).find(node=>node.type==='textarea')!.props.onChange as (e:{target:{value:string}})=>void)({target:{value:reason}});
 hooks.fetching=true;
 for(const locale of ['en','ar']){
  hooks.locale=locale;tree=render();
  expect(nodes(tree).find(node=>node.type==='textarea')?.props.value).toBe(reason);
  expect(JSON.stringify(tree)).toContain(locale==='ar'?'نطاق خاص':'Private scope');
  expect(JSON.stringify(tree)).toContain(locale==='ar'?'شروط دقيقة':'Exact terms');
 }
 expect(hooks.send).not.toHaveBeenCalled();
 hooks.error=new ApiError(403,'denied','');tree=render();
 expect(tree.props.body).toBe(ar.denied);
 expect(nodes(tree).find(node=>node.type==='textarea')).toBeUndefined();
 expect(hooks.slots).not.toContain(reason);
});

it('retains the exact command after malformed or mismatched responses for hold and acceptance',async()=>{
 for(const operation of [undefined,'change-1']){
  for(const update of [null,{}, {schema_version:'unknown'}, {state:'paid'}, {operation_id:'change-2'},
   {subject_id:'job-2'}, {organization_id:'brand-2'}, {actor_id:'buyer-2'}, {watch_id:'watch-2'},
   {expected_revision:5}, {revision:0}, {active_scope_id:'scope-other'}, {execution_authority:true}]){
   hooks.slots=[];hooks.send.mockReset();hooks.locale='en';
   hooks.review={change:fixture.change,scope:{en:'Scope',ar:'نطاق'},terms:{en:'Terms',ar:'شروط'},approval:operation?fixture.approval:null};
   let tree=render(operation);
   if(!operation){
    (nodes(tree).find(node=>node.type==='textarea')!.props.onChange as (e:{target:{value:string}})=>void)({target:{value:'Changed movement'}});
    tree=render(operation);
   }
   hooks.send.mockResolvedValue(update===null?null:Object.keys(update).length===0?{}:{...fixture.responses.success,...update});
   await (button(tree,operation?en.accept:en.start).props.onClick as ()=>Promise<void>)();
   const first=hooks.send.mock.calls[0];
   tree=render(operation);
   expect(JSON.stringify(tree)).toContain(en.unavailable);
   expect(JSON.stringify(tree)).not.toContain(en.reapproved);
   expect(nodes(tree).some(node=>node.type==='a')).toBe(false);
   hooks.locale='ar';
   hooks.review={...hooks.review,change:{...fixture.change,operation_id:'change-2'}};
   tree=render(operation);
   hooks.send.mockResolvedValue(fixture.responses.success);
   await (button(tree,ar.retry).props.onClick as ()=>Promise<void>)();
   expect(hooks.send.mock.calls[1]).toEqual(first);
   tree=render(operation);
   expect(tree.props.body).toBe(ar.reapproved);
   expect(JSON.stringify(tree)).toContain('change-1');
  }
 }
});
