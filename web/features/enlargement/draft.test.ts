import { beforeEach, expect, it, vi } from 'vitest';
import { Children, isValidElement, type ReactElement } from 'react';
import { Input, Checkbox } from '@beirut-time/ui/foundation';
import type { RecordView } from './api';
const state=vi.hoisted(()=>({slots:[] as unknown[],cursor:0,data:undefined as RecordView|undefined}));
vi.mock('react',async()=>({...await vi.importActual('react'),useRef:(initial:unknown)=>{
  const at=state.cursor++;if(!(at in state.slots)) state.slots[at]={current:initial};return state.slots[at];
},useState:(initial:unknown)=>{
  const at=state.cursor++;if(!(at in state.slots)) state.slots[at]=initial;
  return [state.slots[at],(next:unknown)=>{state.slots[at]=typeof next==='function'?next(state.slots[at]):next;}];
}}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=> 'en'}));
vi.mock('@/features/identity/session',()=>({useSession:()=>({access_fingerprint:'synthetic'}),signInHref:()=>'/account'}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:state.data,isPending:false,isError:false,refetch:vi.fn()})}));
vi.mock('./api',()=>({enlargementRead:vi.fn(),submit:vi.fn()}));
import Enlargement from './view';
import { Actions } from './actions';
import { submit } from './api';
import { ApiError } from '@/lib/api/client';
type Node=ReactElement<Record<string,unknown>>;
function nodes(value:unknown):Node[] {
  if(!isValidElement(value)) return [];
  const node=value as Node;
  return [node,...Children.toArray(node.props.children as never).flatMap(nodes)];
}
function page() {
  state.cursor=0;
  const content=Enlargement();
  return (content.type as (props:typeof content.props)=>ReactElement)(content.props);
}
let formSlots:unknown[]=[];
function form(node:Node) {
  const pageSlots=state.slots;
  state.slots=formSlots;state.cursor=0;
  const result=Actions(node.props as Parameters<typeof Actions>[0]);
  formSlots=state.slots;state.slots=pageSlots;
  return result;
}
function action() {return nodes(page()).find(node=>node.type===Actions)!;}
beforeEach(()=>{state.slots=[];state.cursor=0;formSlots=[];vi.mocked(submit).mockReset();});
it.each(['assess','work','accept','fit'])('retains %s details after pending removal, rejection and a newer read',async kind=>{
  state.data={request_id:'synthetic',watch_id:'watch',organization_id:'business',source_revision:1,revision:3,state:'assessed',allowed_operations:[kind],quote_lines:[{id:'line',label_en:'Part',label_ar:'قطعة',amount_minor:100}],quote_terms:{en:'Terms',ar:'شروط'}} as RecordView;
  let node=action();
  const field=nodes(form(node)).find(item=>item.type===Input);
  if(field) (field.props.onValueChange as (value:string)=>void)('Entered قياس 👩🏽‍🔧');
  node=action();
  if(kind==='assess') (node.props.onDraftChange as (draft:unknown)=>void)({...node.props.draft as object,values:{...(node.props.draft as {values:object}).values,minor:'12.50'}});
  node=action();
  const checkbox=nodes(form(node)).find(item=>item.type===Checkbox);
  if(checkbox) (checkbox.props.onCheckedChange as (value:boolean)=>void)(true);
  const expected=action().props.draft;
  let reject!:(error:Error)=>void;
  vi.mocked(submit).mockImplementation(()=>new Promise((_resolve,fail)=>{reject=fail;}));
  const sending=(action().props.submitAction as (body:object)=>Promise<void>)({operation_id:'stable_operation',payload:expected});
  expect(action()).toBeUndefined();
  reject(new ApiError(422,'invalid_input','synthetic'));
  await sending;
  formSlots=[];
  expect(action().props.draft).toEqual(expected);
  state.data={...state.data,revision:4};
  const refreshed=action();
  expect(refreshed.props.draft).toEqual(expected);
  const recovered=nodes(form(refreshed));
  if(field) expect(recovered.find(item=>item.type===Input)?.props.value).toBe('Entered قياس 👩🏽‍🔧');
  if(checkbox) expect(recovered.find(item=>item.type===Checkbox)?.props.checked).toBe(true);
  if(field) (recovered.find(item=>item.type===Input)!.props.onValueChange as (value:string)=>void)('Corrected');
  if(field) expect(nodes(form(action())).find(item=>item.type===Input)?.props.value).toBe('Corrected');
});
it.each(['amount','lines','terms','quoteRevision','termsRevision'])('requires renewed acknowledgement after changed %s',async change=>{
  state.data={request_id:'synthetic',watch_id:'watch',organization_id:'business',source_revision:1,revision:3,state:'assessed',allowed_operations:['accept'],assessment:{quote_id:'quote',quote_revision:1,terms_revision:1,total_minor:100,parts:[],target:'Fit',limitations:'Limited'},quote_lines:[{id:'line',label_en:'Part',label_ar:'قطعة',amount_minor:100}],quote_terms:{en:'Terms',ar:'شروط'}};
  const checkbox=()=>nodes(form(action())).find(item=>item.type===Checkbox)!;
  (checkbox().props.onCheckedChange as (value:boolean)=>void)(true);
  expect(checkbox().props.checked).toBe(true);
  const saved=action().props.draft;
  state.data={...state.data,revision:4};
  expect(checkbox().props.checked).toBe(true);
  const changed=structuredClone(state.data);
  if(change==='amount') changed.quote_lines![0].amount_minor=200;
  if(change==='lines') changed.quote_lines![0].id='replacement';
  if(change==='terms') changed.quote_terms!.ar='شروط جديدة';
  if(change==='quoteRevision') changed.assessment!.quote_revision=2;
  if(change==='termsRevision') changed.assessment!.terms_revision=2;
  state.data=changed;
  expect(checkbox().props.checked).toBe(false);
  expect(action().props.draft).toEqual(saved);
  const blocked=form(action())!;
  await (blocked.props.onSubmit as (event:object)=>Promise<void>)({preventDefault:()=>{}});
  expect(submit).not.toHaveBeenCalled();
  (checkbox().props.onCheckedChange as (value:boolean)=>void)(true);
  expect(checkbox().props.checked).toBe(true);
});
