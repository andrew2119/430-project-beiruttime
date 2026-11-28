import { Children, isValidElement, type ReactElement } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
import { Button, Input } from '@beirut-time/ui/foundation';
import { ApiError } from '../../../../web/lib/api/client';
import { emptyDraft, type Draft } from '../../../../web/features/saved-searches/state';
import { holdPublicDraft, clearPublicDraft } from '../../../../web/features/saved-searches/intent';
import { en, ar } from '../../../../web/features/saved-searches/copy';
const state=vi.hoisted(()=>({slots:[] as unknown[],cursor:0,locale:'en' as 'en'|'ar',fingerprint:'owner' as string|null,session:true,draft:{} as Draft,tab:'searches',readError:null as ApiError|null}));
const api=vi.hoisted(()=>({sendCommand:vi.fn(),lookup:vi.fn(),mutateNotice:vi.fn(),destination:vi.fn(),refetch:vi.fn(),push:vi.fn()}));
vi.mock('react',async()=>({...await vi.importActual('react'),useEffect:()=>{},useLayoutEffect:(effect:()=>void)=>{effect();},useState:(initial:unknown)=>{const at=state.cursor++;if(!(at in state.slots))state.slots[at]=typeof initial==='function'?(initial as ()=>unknown)():initial;return [state.slots[at],(next:unknown)=>{state.slots[at]=typeof next==='function'?(next as (prev:unknown)=>unknown)(state.slots[at]):next;}];},useRef:(initial:unknown)=>{const at=state.cursor++;if(!(at in state.slots))state.slots[at]={current:initial};return state.slots[at];}}));
vi.mock('next/navigation',()=>({useRouter:()=>({push:api.push}),useSearchParams:()=>new URLSearchParams()}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:state.fingerprint,roles:state.session?['buyer']:['public']})}));
vi.mock('@/features/identity/session',()=>({useSession:()=>state.session?{principal:{roles:['buyer']}}:null,useSessionState:()=>state.session?'authenticated':'signed-out',refreshSession:vi.fn(),beginSession:vi.fn()}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:(read:{kind:string}|null)=>({isPending:false,isError:!!state.readError,error:state.readError,refetch:api.refetch,data:read?.kind==='notices'?{total:1,offset:0,limit:20,items:[{id:'notice',revision:1,read:false,event_time:'2026-11-17T12:00:00Z',listing_id:'listing'}]}:{total:0,offset:0,limit:20,items:[]}})}));
vi.mock('@/features/saved-searches/api',()=>({...api,searchesRead:()=>({kind:'searches'}),noticesRead:()=>({kind:'notices'})}));
import SavedSearchView, { Workspace } from '../../../../web/features/saved-searches/view';
import { SignIn } from '../../../../web/features/saved-searches/sign-in';
import { PageReadProvider } from '../../../../web/lib/page-speed/provider';
type View=ReactElement<Record<string,unknown>>;
function elements(view:unknown):View[]{if(!isValidElement(view))return [];const node=view as View;return [node,...Children.toArray(node.props.children as never).flatMap(elements)];}
function draw(){state.cursor=0;return Workspace({fingerprint:state.fingerprint,draft:state.draft,setDraft:draft=>{state.draft=draft;}});}
function button(view:unknown,label:string){return elements(view).find(node=>node.type===Button&&node.props.children===label)!;}
function click(node:View){(node.props.onClick as ()=>void)();}
beforeEach(()=>{state.readError=null;state.slots=[];state.cursor=0;state.locale='en';state.fingerprint='owner';state.session=true;state.draft={...emptyDraft,name:'ساعة Cedar ⌚',q:'long مختلط ⌚',minimum:'٥٫٠١',alerts:true};Object.values(api).forEach(mock=>mock.mockReset());clearPublicDraft();});
it('retains the real form, filters and uncertain command reference while changing language and recovers the same operation',async()=>{
  api.sendCommand.mockRejectedValueOnce(new ApiError(503,'unavailable',''));
  const first=draw();const form=elements(first).find(node=>node.type==='form')!;
  (form.props.onSubmit as (event:unknown)=>void)({preventDefault:vi.fn()});
  await vi.waitFor(()=>expect(button(draw(),en.check)).toBeDefined());
  const original=api.sendCommand.mock.calls[0][0];
  expect(original.criteria.min_minor).toBe(501);
  state.locale='ar';const changed=draw();
  expect(elements(changed).find(node=>node.type===Input&&node.props.label===ar.q)?.props.value).toBe('long مختلط ⌚');
  expect(elements(changed).some(node=>node.type==='bdi'&&node.props.children===original.operation_id)).toBe(true);
  expect(button(changed,ar.save).props.disabled).toBe(true);expect(api.sendCommand).toHaveBeenCalledTimes(1);
  api.lookup.mockResolvedValue({operation_id:original.operation_id,subject_id:original.subject_id,expected_revision:0,state:'saved',result:{id:original.subject_id,revision:1,name:original.name,criteria:original.criteria,alerts_enabled:true,state:'saved',created_at:'2026-11-17T12:00:00Z'}});
  click(button(changed,ar.check));
  await vi.waitFor(()=>expect(state.draft.revision).toBe(1));
  expect(api.lookup.mock.calls[0][0]).toBe(original.operation_id);expect(api.sendCommand).toHaveBeenCalledTimes(1);expect(state.draft.minimum).toBe('5.01');
});
it('uses the actual provider access key and restores public intent across its subtree replacement',()=>{
  state.fingerprint=null;state.session=false;state.cursor=0;
  const publicProvider=PageReadProvider({children:null});expect(publicProvider.key).toBe('public');
  holdPublicDraft(state.draft);
  // Replacing the keyed subtree resets component-local hooks as a real remount does.
  state.slots=[];state.cursor=0;state.fingerprint='new-owner';state.session=true;
  const memberProvider=PageReadProvider({children:null});expect(memberProvider.key).toBe('member:new-owner');
  state.cursor=0;const view=SavedSearchView();
  const workspace=elements(view).find(node=>node.type===Workspace)!;
  expect(workspace.props.draft).toEqual(state.draft);
  state.slots=[];state.cursor=0;state.fingerprint='other-owner';
  expect(elements(SavedSearchView()).find(node=>node.type===Workspace)!.props.draft).toEqual(emptyDraft);
});
it('reloads current notice state after a stale read mutation and exposes explicit recovery',async()=>{
  // The tab state is controlled by the actual Segmented callback.
  let view=draw();const tabs=elements(view).find(node=>(node.props.options as {value:string}[]|undefined)?.some(option=>option.value==='notices'))!;
  (tabs.props.onValueChange as (value:string)=>void)('notices');view=draw();
  api.mutateNotice.mockRejectedValueOnce(new ApiError(409,'stale_revision',''));
  click(button(view,en.read));
  await vi.waitFor(()=>expect(button(draw(),en.reload)).toBeDefined());
  expect(api.refetch).toHaveBeenCalled();click(button(draw(),en.reload));expect(api.refetch).toHaveBeenCalledTimes(2);
});

it('preserves password and email in the same sign-in form across language changes without submitting',()=>{
  const drawSignIn=()=>{state.cursor=0;return SignIn({label:state.locale==='ar'?ar.signin:en.signin,onIntent:vi.fn(),onCancel:vi.fn()});};
  const first=drawSignIn();
  const fields=elements(first).filter(node=>node.type===Input);
  (fields[0].props.onValueChange as (value:string)=>void)('synthetic@example.test');
  (fields[1].props.onValueChange as (value:string)=>void)('private-memory-value');
  state.locale='ar';
  const second=elements(drawSignIn()).filter(node=>node.type===Input);
  expect(second[0].props.value).toBe('synthetic@example.test');expect(second[1].props.value).toBe('private-memory-value');
  expect(second[1].props.type).toBe('password');expect(api.sendCommand).not.toHaveBeenCalled();
});

it('keeps the executable route withheld pending shared admission',async()=>{
  const {existsSync}=await import('node:fs');
  const {default:registration}=await import('../../../../web/features/saved-searches/registration');
  expect(existsSync(new URL('../../../../web/app/(saved-searches)/saved-searches/page.tsx',import.meta.url))).toBe(false);
  expect(registration.routes).toEqual([]);expect(registration.navigation).toEqual([]);
});

for(const locale of ['en','ar'] as const)for(const code of [401,403]){
  it(`shows account recovery for a ${code} read denial in ${locale}`,()=>{
    state.locale=locale;state.readError=new ApiError(code,'forbidden','');
    const nodes=elements(draw()),copy=locale==='ar'?ar:en;
    expect(nodes.some(node=>node.props.title===copy.denied)).toBe(true);
    expect(nodes.some(node=>node.props.href===`/${locale}/account`&&node.props.children===copy.recoverAccess)).toBe(true);
    expect(button(draw(),copy.retry)).toBeUndefined();
  });
  it(`shows account recovery for a ${code} notice denial in ${locale}`,async()=>{
    state.locale=locale;const copy=locale==='ar'?ar:en;
    const tabs=elements(draw()).find(node=>(node.props.options as {value:string}[]|undefined)?.some(option=>option.value==='notices'))!;
    (tabs.props.onValueChange as (value:string)=>void)('notices');
    api.mutateNotice.mockRejectedValueOnce(new ApiError(code,'forbidden',''));
    click(button(draw(),copy.read));
    await vi.waitFor(()=>expect(elements(draw()).some(node=>node.props.children===copy.denied)).toBe(true));
    expect(elements(draw()).some(node=>node.props.href===`/${locale}/account`)).toBe(true);
    expect(button(draw(),copy.retry)).toBeUndefined();
  });
}

for(const [initial,current] of [['en','ar'],['ar','en']] as const){
  it(`opens a pending notice in the current ${current} language`,async()=>{
    state.locale=initial;
    const tabs=elements(draw()).find(node=>(node.props.options as {value:string}[]|undefined)?.some(option=>option.value==='notices'))!;
    (tabs.props.onValueChange as (value:string)=>void)('notices');
    let resolve!:(value:{href:string})=>void;
    api.destination.mockReturnValueOnce(new Promise<{href:string}>(done=>{resolve=done;}));
    click(button(draw(),(initial==='ar'?ar:en).open));
    expect(api.destination).toHaveBeenCalledTimes(1);
    state.locale=current;draw();
    const href='/watches/50000000-0000-4000-8000-000000000001';
    resolve({href});
    await vi.waitFor(()=>expect(api.push).toHaveBeenCalledWith(`/${current}${href}`));
    expect(api.destination).toHaveBeenCalledTimes(1);
  });
}
