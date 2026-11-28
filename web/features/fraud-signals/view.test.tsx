import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
const state=vi.hoisted(()=>({locale:'en',session:true,status:'authenticated',query:'',page:1,inputs:[] as {onValueChange:(value:string)=>void}[],reads:[] as unknown[],error:false}));
vi.mock('react',async()=>{
  const actual=await vi.importActual<typeof import('react')>('react');
  return {...actual,useState:(initial:unknown)=>typeof initial==='number'?[state.page,(value:(old:number)=>number)=>{state.page=value(state.page);}]:[state.query,(value:string)=>{state.query=value;}]};
});
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/features/identity/session',()=>({useSession:()=>state.session?{access_fingerprint:'current-access'}:null,useSessionState:()=>state.status,refreshSession:vi.fn(),authenticatedRequest:vi.fn()}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:(read:unknown)=>{
  state.reads.push(read);
  return {isPending:false,isError:state.error,isFetching:false,error:null,refetch:vi.fn(),data:state.error?undefined:{total:1000,page_size:20,items:[{operation_id:'operation-0001',state:'review_required',reasons:[{kind:'exact_photo_reuse',count:1}],next_review_at:'2026-11-18T00:00:00Z'}]}};
}}));
vi.mock('@beirut-time/ui/foundation',async()=>{
  const actual=await vi.importActual<typeof import('@beirut-time/ui/foundation')>('@beirut-time/ui/foundation');
  return {...actual,Input:(props:{id:string;value:string;onValueChange:(value:string)=>void})=>{state.inputs.push(props);return <input id={props.id} value={props.value} readOnly/>;}};
});
vi.mock('next/navigation',()=>({usePathname:()=>'/internal/signals'}));
import SignalsView from './view';
beforeEach(()=>{state.locale='en';state.session=true;state.status='authenticated';state.query='';state.page=1;state.inputs=[];state.reads=[];state.error=false;});
it('retains filter, page, read key and exact reference across locale render boundaries',()=>{
  renderToStaticMarkup(<SignalsView/>);
  state.inputs[0].onValueChange('operation-0001');
  state.page=2;
  const english=renderToStaticMarkup(<SignalsView/>);
  const read=state.reads.at(-1) as {key:unknown[]};
  state.locale='ar';
  const arabic=renderToStaticMarkup(<SignalsView/>);
  expect(arabic).toContain('value="operation-0001"');
  expect(arabic).toContain('operation-0001');
  expect(arabic).toContain('مراجعة يدوية');
  expect(english).toContain('Manual review required');
  expect((state.reads.at(-1) as {key:unknown[]}).key).toEqual(read.key);
  expect(state.page).toBe(2);
  const source=readFileSync(new URL('./view.tsx',import.meta.url),'utf8');
  expect(source).toContain('key={session.access_fingerprint}');
  expect(source).not.toMatch(/key=\{locale\}|localStorage|sessionStorage/);
});
it('distinguishes restoring, denied, unavailable and empty states in both languages',()=>{
  for(const locale of ['en','ar']) {
    state.locale=locale;state.session=false;state.status='restoring';
    expect(renderToStaticMarkup(<SignalsView/>)).toContain('aria-busy="true"');
    state.status='unavailable';
    expect(renderToStaticMarkup(<SignalsView/>)).toContain('role="alert"');
    state.status='signed-out';
    expect(renderToStaticMarkup(<SignalsView/>)).toContain(locale==='en'?'Access denied':'الوصول مرفوض');
    state.session=true;state.query='missing';
    expect(renderToStaticMarkup(<SignalsView/>)).toContain(locale==='en'?'No matching signals':'لا توجد إشارات مطابقة');
  }
});
