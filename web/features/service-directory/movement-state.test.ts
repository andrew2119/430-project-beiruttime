import { expect, it, vi, beforeEach } from 'vitest';
import type { ReactElement } from 'react';
const state=vi.hoisted(()=>({slots:[] as unknown[],cursor:0,send:vi.fn(),withdrawn:false,archived:false,revision:1,error:null as unknown}));
vi.mock('react',async importOriginal=>({...await importOriginal<typeof import('react')>(),useId:()=>'movement-heading',useEffect:()=>{},useState:(initial:unknown)=>{
  const index=state.cursor++;if(!(index in state.slots))state.slots[index]=initial;
  return [state.slots[index],(value:unknown)=>{state.slots[index]=typeof value==='function'?value(state.slots[index]):value;}];
}}));
vi.mock('@beirut-time/ui/foundation',()=>({Button:'button-control',Input:'input-control',Select:'select-control',Card:'card-control',State:'state-control',formatNumber:String}));
vi.mock('../movement-option/offering',()=>({MovementOffering:'offering-control'}));
vi.mock('../movement-option/money',()=>({formatMinor:()=>'$250.00'}));
vi.mock('@/features/identity/session',()=>({useSession:()=>null}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>'en'}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({roles:['buyer'],fingerprint:'synthetic'})}));
vi.mock('./api',()=>({directoryPath:'/api/directory',movementPath:'/api/movement',privateRequest:vi.fn(),useJsonCommand:()=>state.send,useCommandMutation:({mutationFn}:{mutationFn:()=>Promise<unknown>})=>({mutate:mutationFn,reset:vi.fn(),isPending:false,isError:false,needsRecovery:false})}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:(read:{key:unknown[]}|null)=>{
  const option=(id:string)=>({id,brand_id:'brand',revision:state.revision,label_en:id,label_ar:id,caliber:id,cases:['case'],dials:['dial'],hands:['hands'],functions:[],quote_minor:25000,currency:'USD'});
  const key=read?.key[0];
  return {data:key==='movement-options'?{items:[option(read?.key[2]?'second':'first')],total:2,next_after:read?.key[2]?null:'cursor'}:key==='movement-option'?(state.withdrawn?undefined:{item:option(String(read?.key[1]))}):key==='movement-selection'?{selection:state.withdrawn?{id:'saved',option_id:'withdrawn',revision:4,option_revision:1,configuration:{case:'historic',dial:'dial',hands:'hands',functions:[]},status:'manual_review',quote_impact:{minor:25000,currency:'USD'}}:null,archived:state.archived,selection_revision:state.archived||state.withdrawn?4:0}:undefined,error:key==='movement-selection'?state.error:null,isPending:false,isError:key==='movement-selection'&&Boolean(state.error),isFetching:false,isSuccess:!state.error,refetch:vi.fn()};
}}));
import { ApiError } from '@/lib/api/client';
import MovementOption from '../movement-option/view';
import en from '../movement-option/en.json';
function render(){state.cursor=0;return MovementOption({brandId:'brand',sample:true});}
function elements(node:unknown):ReactElement<Record<string,unknown>>[]{
  if(Array.isArray(node))return node.flatMap(elements);
  if(!node||typeof node!=='object'||!('props' in node))return [];
  const element=node as ReactElement<Record<string,unknown>>;
  return [element,...elements(element.props.children)];
}
function control(tree:unknown,label:string){return elements(tree).find(item=>item.props.label===label)!;}
beforeEach(()=>{state.slots=[];state.cursor=0;state.withdrawn=false;state.archived=false;state.revision=1;state.error=null;state.send.mockReset();state.send.mockResolvedValue({revision:1});});
it.each(['case','functions'] as const)('pins the implicit first movement when editing %s before paging and saves that exact option',async field=>{
  let tree=render();
  const input=control(tree,en[field]);
  (input.props.onValueChange as (text:string)=>void)('unsent');
  tree=render();
  const next=elements(tree).find(item=>item.props.children===en.more)!;
  (next.props.onClick as ()=>void)();
  tree=render();
  expect(control(tree,en.option).props.value).toBe('first');
  expect(control(tree,en[field]).props.value).toBe('unsent');
  const form=elements(tree).find(item=>item.type==='form')!;
  await (form.props.onSubmit as (event:{preventDefault:()=>void})=>Promise<unknown>)({preventDefault:()=>{}});
  expect(state.send.mock.calls[0][1].option_id).toBe('first');
  expect(state.send.mock.calls[0][1].configuration[field]).toEqual(field==='functions'?['unsent']:'unsent');
});

it('keeps current alternatives reachable when the saved movement was withdrawn',async()=>{
  state.withdrawn=true;
  let tree=render();
  const replacement=control(tree,en.replacement);
  expect(replacement).toBeDefined();
  (replacement.props.onValueChange as (id:string)=>void)('first');
  tree=render();
  expect(control(tree,en.option).props.value).toBe('first');
  const form=elements(tree).find(item=>item.type==='form')!;
  await (form.props.onSubmit as (event:{preventDefault:()=>void})=>Promise<unknown>)({preventDefault:()=>{}});
  expect(state.send.mock.calls[0][1]).toMatchObject({option_id:'first',expected_revision:4});
});
it('uses safe archived revision metadata for an explicit current USD selection',async()=>{
  state.archived=true;
  const tree=render();
  const form=elements(tree).find(item=>item.type==='form')!;
  await (form.props.onSubmit as (event:{preventDefault:()=>void})=>Promise<unknown>)({preventDefault:()=>{}});
  expect(state.send.mock.calls[0][1]).toMatchObject({option_id:'first',expected_revision:4});
});

it.each(['pending', 'recovery'])('blocks movement replacement during staff %s and restores it after resolution',()=>{
  let tree=render();
  const offering=elements(tree).find(item=>item.type==='offering-control')!;
  (offering.props.onLockChange as (locked:boolean)=>void)(true);
  tree=render();
  const selector=control(tree,en.option);
  expect(selector.props.disabled).toBe(true);
  (selector.props.onValueChange as (id:string)=>void)('second');
  tree=render();
  expect(control(tree,en.option).props.value).toBe('first');
  expect(elements(tree).find(item=>item.props.children===en.more)?.props.disabled).toBe(true);
  (offering.props.onLockChange as (locked:boolean)=>void)(false);
  tree=render();
  expect(control(tree,en.option).props.disabled).toBe(false);
});

it.each(['case','functions'] as const)('requires explicit revision review while retaining the %s draft',async field=>{
  let tree=render();
  (control(tree,en[field]).props.onValueChange as (value:string)=>void)('unsent');
  state.revision=2;
  tree=render();
  expect(control(tree,en[field]).props.value).toBe('unsent');
  expect(elements(tree).find(item=>item.props.type==='submit')?.props.disabled).toBe(true);
  const submit=async()=>{
    const form=elements(tree).find(item=>item.type==='form')!;
    await (form.props.onSubmit as (event:{preventDefault:()=>void})=>void)({preventDefault:()=>{}});
  };
  await submit();
  expect(state.send).not.toHaveBeenCalled();
  expect(elements(tree).some(item=>item.props.children===en.reviewChanged)).toBe(true);
  (elements(tree).find(item=>item.props.children===en.reviewCurrent)!.props.onClick as ()=>void)();
  tree=render();
  expect(control(tree,en[field]).props.value).toBe('unsent');
  expect(elements(tree).find(item=>item.props.type==='submit')?.props.disabled).toBe(false);
  await submit();
  expect(state.send.mock.calls[0][1]).toMatchObject({option_id:'first',option_revision:2});
  expect(state.send.mock.calls[0][1].configuration[field]).toEqual(field==='functions'?['unsent']:'unsent');
});

it.each([401,403,404])('suppresses retained requirements and clears drafts after denial %s',status=>{
  state.withdrawn=true;
  let tree=render();
  expect(JSON.stringify(tree)).toContain('historic');
  state.withdrawn=false;
  (control(tree,en.replacement).props.onValueChange as (id:string)=>void)('first');
  tree=render();
  (control(tree,en.case).props.onValueChange as (text:string)=>void)('private draft');
  state.error=new ApiError(503,'unavailable','');
  tree=render();
  expect(control(tree,en.case).props.value).toBe('private draft');
  state.error=new ApiError(status,'forbidden','');
  tree=render();
  expect(elements(tree).some(item=>item.type==='form')).toBe(false);
  expect(JSON.stringify(tree)).not.toContain('private draft');
  state.error=new ApiError(503,'unavailable','');
  tree=render();
  expect(elements(tree).some(item=>item.type==='form')).toBe(false);
  state.error=null;
  render();tree=render();
  expect(control(tree,en.case).props.value).toBe('case');
});
