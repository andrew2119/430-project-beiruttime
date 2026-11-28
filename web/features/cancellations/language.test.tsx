import {beforeEach,describe,expect,it,vi} from 'vitest';
import type {ReactElement,ReactNode} from 'react';

// Component state is retained by type, position and key across each render.
const mounted=vi.hoisted(()=>({slots:new Map<string,unknown[]>(),path:'',index:0,
 locale:'en' as 'en'|'ar',fingerprint:'scope-one',request:vi.fn()}));
vi.mock('react',async importOriginal=>{
 const actual=await importOriginal<typeof import('react')>();
 function slot<T>(initial:T):[T,(value:T)=>void]{
  const values=mounted.slots.get(mounted.path)??[];
  mounted.slots.set(mounted.path,values);
  const index=mounted.index++;
  if(!(index in values))values[index]=initial;
  return [values[index] as T,value=>{values[index]=value;}];
 }
 return {...actual,useState:<T,>(initial:T)=>slot(initial),useRef:<T,>(initial:T)=>slot({current:initial})[0]};
});
vi.mock('@beirut-time/ui',()=>Object.fromEntries([
 'BidiReference','Button','ButtonLink','Card','Input','Label','LoadingRows','Notice','SectionState','Segmented','StatusBadge',
].map(name=>[name,name])));
vi.mock('@/shell/page-header',()=>({PageLayout:'PageLayout',PageHeader:'PageHeader'}));
vi.mock('./locale',()=>({useCancellationLocale:()=>({locale:mounted.locale,changeLocale:(next:'en'|'ar')=>{mounted.locale=next;}})}));
vi.mock('@/features/identity/session',()=>({useSession:()=>({access_fingerprint:mounted.fingerprint}),
 useSessionState:()=> 'authenticated',signInHref:()=>'/en/account',authenticatedRequest:mounted.request}));
import Cancellations from './page';
import {ApiError} from '@/lib/api/client';

type Element=ReactElement<Record<string,unknown>>;
let nodes:Element[]=[];
function render(){
 nodes=[];
 const seen=new Set<string>();
 function walk(node:ReactNode,path:string):void{
  if(Array.isArray(node)){node.forEach((child,index)=>walk(child,`${path}/${index}`));return;}
  if(!node||typeof node!=='object'||!('props' in node))return;
  const element=node as Element;
  const identity=`${path}/${String(element.key??'')}/${typeof element.type==='function'?element.type.name:String(element.type)}`;
  if(typeof element.type==='function'){
   seen.add(identity);mounted.path=identity;mounted.index=0;
   walk((element.type as (props:Record<string,unknown>)=>ReactNode)(element.props),identity);
  }else{
   nodes.push(element);
   walk(element.props.tools as ReactNode,`${identity}/tools`);
   walk(element.props.children as ReactNode,`${identity}/children`);
  }
 }
 walk(<Cancellations/>,'root');
 for(const key of mounted.slots.keys())if(!seen.has(key))mounted.slots.delete(key);
}
function find(type:string,predicate:(props:Record<string,unknown>)=>boolean=()=>true){
 const node=nodes.find(node=>node.type===type&&predicate(node.props));
 expect(node).toBeDefined();return node!.props;
}
function change(id:string,value:string){
 (find('Input',props=>props.id===id).onChange as (event:unknown)=>void)({target:{value}});render();
}
function language(value:'en'|'ar'){
 (find('Segmented').onChange as (value:string)=>void)(value);render();
 expect(find('div').dir).toBe(value==='ar'?'rtl':'ltr');
 expect(find('div').lang).toBe(value);
}
function click(label:string){return (find('Button',props=>props.children===label).onClick as ()=>Promise<void>|void)();}
function submit(){(find('form').onSubmit as (event:unknown)=>void)({preventDefault(){}});render();}
const subject='00000000-0000-4000-8000-000000000001';
const watch='00000000-0000-4000-8000-000000000002';
const note='ساعة ABC — '+ 'تفاصيل طويلة '.repeat(20)+'⌚';
beforeEach(()=>{mounted.slots.clear();mounted.locale='en';mounted.fingerprint='scope-one';mounted.request.mockReset();render();});
function draft(){change('cancel-subject',subject);change('cancel-watch',watch);change('cancel-revision','4');change('cancel-reason',note);}

describe('in-place cancellation language journey',()=>{
 it('keeps the same form, draft and saved reference without sending a request',()=>{
  draft();change('cancel-saved',subject);
  const formSlots=[...mounted.slots.values()];
  language('ar');
  expect(find('PageHeader').title).toBe('طلب الإلغاء أو التراجع');
  expect(find('Input',p=>p.id==='cancel-reason').value).toBe(note);
  expect(find('Input',p=>p.id==='cancel-saved').value).toBe(subject);
  language('en');
  expect(find('Input',p=>p.id==='cancel-subject').value).toBe(subject);
  expect([...mounted.slots.values()]).toEqual(formSlots);
  expect(mounted.request).not.toHaveBeenCalled();
 });
 it('keeps an in-flight and uncertain command through both languages and retries identical bytes',async()=>{
  let fail: (reason:Error)=>void=()=>{};
  mounted.request.mockImplementationOnce(()=>new Promise((_,reject)=>{fail=reject;}));
  draft();submit();
  const [url,options]=mounted.request.mock.calls[0];
  const command=JSON.parse(options.body);
  language('ar');
  expect(find('Button',p=>p.type==='submit').disabled).toBe(true);
  expect(mounted.request).toHaveBeenCalledTimes(1);
  fail(new Error('response unavailable'));
  await vi.waitFor(()=>{render();expect(find('SectionState').title).toContain('النتيجة غير متاحة');});
  language('en');
  expect(find('Input',p=>p.id==='cancel-reason').value).toBe(note);
  expect(nodes.some(n=>n.type==='BidiReference'&&n.props.children===command.operation_id)).toBe(true);
  mounted.request.mockResolvedValueOnce({...command,state:'pending',pending_reason:'decision_required',refundable_minor:0,completed:false,next_review_at:null});
  submit();
  await vi.waitFor(()=>{render();expect(nodes.some(n=>n.type==='StatusBadge')).toBe(true);});
  expect(mounted.request.mock.calls[1]).toEqual([url,options]);
  language('ar');
  expect(mounted.request).toHaveBeenCalledTimes(2);
  expect(find('StatusBadge').children).toBe('بانتظار المراجعة');
  mounted.request.mockRejectedValueOnce(new Error('unavailable'));
  click('التحقق من العملية');
  await vi.waitFor(()=>expect(mounted.request).toHaveBeenCalledTimes(3));
  expect(mounted.request.mock.calls[2][0]).toContain(`/operations/${command.operation_id}?subject_id=${subject}`);
  expect(mounted.request.mock.calls[2][1].method).toBe('GET');
 });
 it('retains a lost operation through denied retry and restored access',async()=>{
  mounted.request.mockRejectedValueOnce(new Error('response unavailable'));
  draft();submit();
  await vi.waitFor(()=>{render();expect(find('SectionState').title).toContain('outcome is unavailable');});
  const [url,options]=mounted.request.mock.calls[0];
  const command=JSON.parse(options.body);
  mounted.request.mockRejectedValueOnce(new ApiError(403,'scope_denied','test-reference'));
  submit();
  await vi.waitFor(()=>{render();expect(find('SectionState').title).toContain('Access or request denied');});
  expect(nodes.some(n=>n.type==='Button'&&n.props.children==='Review current order details')).toBe(false);
  expect(find('Input',p=>p.id==='cancel-subject').disabled).toBe(true);
  expect(find('ButtonLink',p=>p.children==='Contact support').href).toBe(`/en/inbox?operation_id=${command.operation_id}`);
  language('ar');
  expect(find('ButtonLink',p=>p.children==='التواصل مع الدعم').href).toBe(`/ar/inbox?operation_id=${command.operation_id}`);
  mounted.request.mockResolvedValueOnce({...command,state:'accepted',pending_reason:null,refundable_minor:0,completed:true,next_review_at:null});
  submit();
  await vi.waitFor(()=>{render();expect(find('StatusBadge').children).toBe('مقبول');});
  expect(mounted.request.mock.calls[1]).toEqual([url,options]);
  expect(mounted.request.mock.calls[2]).toEqual([url,options]);
 });
 it('clears private form state when access changes',()=>{
  draft();language('ar');mounted.fingerprint='scope-two';render();
  expect(find('Input',p=>p.id==='cancel-reason').value).toBe('');
 });
});
