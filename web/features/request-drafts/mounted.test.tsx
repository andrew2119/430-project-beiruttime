import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { ApiError } from '../../lib/api/client';
import fixture from '../../../packages/contracts-catalog/request-drafts/fixtures/request.v2.json';
import { purge, recall } from './memory';

// Minimal document for mounted state checks; viewport and focus checks run separately.
class TestNode {
  nodeType = 1;
  nodeName: string;
  tagName: string;
  namespaceURI = 'http://www.w3.org/1999/xhtml';
  ownerDocument: TestDocument;
  parentNode: TestNode | null = null;
  childNodes: TestNode[] = [];
  style = {};
  attributes: Record<string, string> = {};
  private text = '';
  constructor(name: string, document: TestDocument) { this.nodeName = this.tagName = name.toUpperCase(); this.ownerDocument = document; }
  appendChild(node: TestNode) { node.parentNode = this; this.childNodes.push(node); return node; }
  removeChild(node: TestNode) { this.childNodes.splice(this.childNodes.indexOf(node), 1); node.parentNode = null; return node; }
  insertBefore(node: TestNode, before: TestNode) { node.parentNode = this; this.childNodes.splice(this.childNodes.indexOf(before), 0, node); return node; }
  setAttribute(name: string, value: string) { this.attributes[name] = String(value); }
  removeAttribute(name: string) { delete this.attributes[name]; }
  addEventListener() {}
  removeEventListener() {}
  get textContent(): string { return this.text + this.childNodes.map(node => node.textContent).join(''); }
  set textContent(value: string) { this.text = value; this.childNodes = []; }
}
class TestDocument {
  nodeType = 9;
  activeElement = null;
  defaultView = {};
  createElement(name: string) { return new TestNode(name, this); }
  createElementNS(_namespace: string, name: string) { return this.createElement(name); }
  createTextNode(text: string) { const node = new TestNode('#text', this); node.nodeType = 3; node.textContent = text; return node; }
  addEventListener() {}
  removeEventListener() {}
}
const state = vi.hoisted(() => ({ locale: 'en', search: new URLSearchParams('configuration=config&revision=3'), denied: 0, session: true, submitted: false, readTarget:'', readStatus:0, commands: [] as {key:string;body:string}[] }));
vi.mock('next/navigation', () => ({ useSearchParams: () => state.search, useRouter: () => ({ refresh: () => {} }) }));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => state.locale }));
vi.mock('@/shell/access-context', () => ({ useAccessContext: () => ({ fingerprint: 'buyer' }) }));
vi.mock('@/features/identity/session', () => ({
  useSession: () => state.session?({ access_fingerprint: 'buyer' }):null, signInHref: () => '/sign-in',
  authenticatedRequest: async (_url: string, options?: {method?:string;headers:Record<string,string>;body:string}) => {
    if (options?.method === 'POST') { state.commands.push({key:options.headers['Idempotency-Key'],body:options.body}); throw new Error('Response lost'); }
    if(_url.includes('/revisions')) {
      if(state.readTarget==='history'&&state.readStatus)throw new ApiError(state.readStatus,'forbidden','history-read');
      return {items:[{...fixture.request,actor_id:fixture.request.buyer_id,reason:'Private correction'}],current_revision:1,total:1,next_cursor:null};
    }
    if(_url.endsWith('/decision')) {
      if(state.readTarget==='decision'&&state.readStatus)throw new ApiError(state.readStatus,'forbidden','decision-read');
      return {status:'pending',execution_authority:false};
    }
    return { items: state.submitted?[{...fixture.request,draft_id:'draft'}]:[] };
  },
}));
vi.mock('@/features/brand-options/configuration-review', () => ({ configurationApi: {
  movement: async () => ({selection:{id:'movement',revision:1}}),
  validate: async () => ({status:'manual_assessment',digest:'a'.repeat(64),snapshot:{selections:{},reference_ids:[]}}),
} }));
vi.mock('@/features/brand-options/configuration-copy', () => ({ configurationField: () => '', configurationSelectionLabel: () => '' }));
vi.mock('./api', () => ({ draftApi: {
  configuration: async (id:string,revision:number) => ({configuration_id:id,configuration_revision:revision,brand_id:'brand',options:{}}),
  get: async (id:string) => ({...draft,id,watch_reference:'Watch '+id}),
  list: async () => { if(state.denied) throw new ApiError(state.denied,'forbidden','denied-read'); return {items:[draft],total:1,next_cursor:null}; },
  catalogue: async () => ({status:'available',data:{items:[],next_after:null}}),
  readiness: async () => ({draft,options:null}),
  save: async () => ({draft}),
} }));
vi.mock('@beirut-time/ui', () => {
  const Box = ({children}:{children?:ReactNode}) => <div>{children}</div>;
  return { BidiReference:({children}:{children?:ReactNode})=><bdi>{children}</bdi>, Card:Box, StatusBadge:Box, ButtonLink:Box,
    Button:({children,onClick,disabled,type}:{children?:ReactNode;onClick?:()=>void;disabled?:boolean;type?:'submit'})=><button onClick={onClick} disabled={disabled} type={type}>{children}</button>,
    Input:({value}:{value:string})=><input value={value} readOnly/>, Textarea:({value}:{value:string})=><textarea value={value} readOnly/>,
    State:({body,children}:{body:string;children?:ReactNode})=><div>{body}{children}</div>,
    Select:Box, Segmented:Box, AnimatedList:({items,children}:{items:typeof draft[];children:(item:typeof draft)=>ReactNode})=><div>{items.map(item=><div key={item.id}>{children(item)}</div>)}</div>,
  };
});
vi.mock('@/shell/page-header', () => ({ PageLayout:({children}:{children:ReactNode})=><div>{children}</div>, PageHeader:()=>null }));
import RequestDrafts from './request-drafts';
import { changeRequestLocale } from './locale';
const draft = {id:'draft',revision:1,kind:'customization',brand_id:'brand',configuration_id:'config',configuration_revision:3,watch_context:'owned_watch',watch_reference:'Private watch نص ⌚',scope_intent:'Private scope',notes:'Private notes',options:{},updated_at:'2026-11-16T00:00:00Z'};
let root:Root, container:TestNode, cache:QueryClient;
let accessChanged:()=>void;
async function settle() { await act(async()=>{await new Promise(resolve=>setTimeout(resolve,80));}); }
async function mount(session=true) {
  purge(); state.session=session;state.submitted=false;state.readTarget='';state.readStatus=0; state.locale='en';state.denied=0;state.commands=[];state.search=new URLSearchParams('configuration=config&revision=3');
  const document = new TestDocument(); container=document.createElement('div');
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  vi.stubGlobal('document',document);
  vi.stubGlobal('window',{document,HTMLIFrameElement:class {},location:{href:'https://example.test/en/custom-requests?configuration=config&revision=3'},history:{state:{},replaceState:(_data:unknown,_unused:string,url:URL)=>{window.location.href=String(url);}},addEventListener:(name:string,listener:()=>void)=>{if(name==='bt:access-change')accessChanged=listener;},removeEventListener:()=>{}});
  document.defaultView=window;
  cache=new QueryClient({defaultOptions:{queries:{retry:false,gcTime:Infinity}}});
  root=createRoot(container as unknown as HTMLElement); await render(); await settle();
}
async function render() { await act(async()=>root.render(<QueryClientProvider client={cache}><RequestDrafts/></QueryClientProvider>)); }
function nodes(node:TestNode):TestNode[] { return [node,...node.childNodes.flatMap(nodes)]; }
function props(node:TestNode):Record<string,unknown> { const key=Object.keys(node).find(key=>key.startsWith('__reactProps')); return key?(node as unknown as Record<string,Record<string,unknown>>)[key]:{}; }
async function click(text:string) { const button=nodes(container).find(node=>node.tagName==='BUTTON'&&!hidden(node)&&node.textContent===text); expect(button).toBeDefined(); expect(props(button!).disabled).not.toBe(true); await act(async()=>{(props(button!).onClick as ()=>void)();});await settle(); }
afterEach(async()=>{if(root)await act(async()=>root.unmount());cache?.clear();purge();vi.unstubAllGlobals();});

it('keeps the mounted submission and exact retry after save and language query synchronization',async()=>{
  await mount();
  const form=nodes(container).find(node=>node.tagName==='FORM')!;
  await act(async()=>{(props(form).onSubmit as (event:{preventDefault:()=>void})=>void)({preventDefault:()=>{}});});await settle();
  await click('Review current dimensions');await click('Submit reviewed revision');
  expect(state.commands).toHaveLength(1);
  const mountedForm=nodes(container).find(node=>node.tagName==='FORM');
  class LocaleLink { closest() { return {href:'https://example.test/ar/custom-requests?configuration=config&revision=3'}; } }
  vi.stubGlobal('Element',LocaleLink);
  const refresh=vi.fn(()=>{state.locale='ar';state.search=new URLSearchParams(new URL(window.location.href).search);});
  changeRequestLocale({target:new LocaleLink(),button:0,preventDefault:vi.fn(),stopPropagation:vi.fn()} as unknown as MouseEvent,refresh);
  expect(refresh).toHaveBeenCalledOnce();
  expect(state.search.get('draft')).toBe('draft');
  expect(state.search.has('configuration')).toBe(false);
  expect(state.commands).toHaveLength(1);
  await render();await settle();
  expect(nodes(container).find(node=>node.tagName==='FORM')).toBe(mountedForm);
  await click('تسوية نفس عملية الإرسال');
  expect(state.commands).toHaveLength(2);expect(state.commands[1]).toEqual(state.commands[0]);
});

it.each([401,403])('clears cached records and the editor after a list refresh returns %s',async status=>{
  await mount();expect(container.textContent).toContain(draft.watch_reference);
  state.denied=status;
  await act(async()=>{await cache.invalidateQueries({queryKey:['l08-drafts','buyer']});});await settle();
  expect(container.textContent).not.toContain(draft.watch_reference);
  expect(container.textContent).not.toContain(draft.notes);
  expect(nodes(container).some(node=>node.tagName==='FORM')).toBe(false);
  expect(cache.getQueryData(['l08-drafts','buyer'])).toBeUndefined();
  expect(recall('buyer')).toBeNull();
  expect(JSON.stringify(cache.getQueryCache().getAll().map(query=>query.state.data))).not.toContain(draft.watch_reference);
  expect(container.textContent).toContain('Current permissions');
});

it('keeps private input mounted during an unavailable list refresh',async()=>{
  await mount();const form=nodes(container).find(node=>node.tagName==='FORM');
  state.denied=503;
  await act(async()=>{await cache.invalidateQueries({queryKey:['l08-drafts','buyer']});});await settle();
  expect(nodes(container).find(node=>node.tagName==='FORM')).toBe(form);
  expect(container.textContent).toContain(draft.watch_reference);
});

it('clears and rechecks private access on a current access change',async()=>{
  await mount();expect(container.textContent).toContain(draft.watch_reference);
  state.denied=403;
  await act(async()=>accessChanged());await settle();
  expect(nodes(container).some(node=>node.tagName==='FORM')).toBe(false);
  expect(container.textContent).not.toContain(draft.watch_reference);
  expect(recall('buyer')).toBeNull();
  expect(cache.getQueryData(['l08-drafts','buyer'])).toBeUndefined();
});

it('restores an authenticated configuration entry without a false denial or losing its source',async()=>{
  await mount(false);
  expect(nodes(container).some(node=>node.tagName==='FORM')).toBe(false);
  state.session=true;
  await act(async()=>accessChanged());await render();await settle();
  expect(nodes(container).some(node=>node.tagName==='FORM')).toBe(true);
  expect(container.textContent).not.toContain('Current permissions');
  expect(recall('buyer')?.form.configuration_id).toBe('config');
  expect(state.search.get('configuration')).toBe('config');
  expect(new URL(window.location.href).searchParams.get('configuration')).toBe('config');
  expect(state.commands).toHaveLength(0);
});

it.each(['history','decision'])('fences all private request content after a denied %s refresh',async target=>{
  await mount();
  const form=nodes(container).find(node=>node.tagName==='FORM')!;
  await act(async()=>{(props(form).onSubmit as (event:{preventDefault:()=>void})=>void)({preventDefault:()=>{}});});await settle();
  state.submitted=true;
  await act(async()=>{await cache.invalidateQueries({queryKey:['customization-requests','buyer']});});await settle();
  expect(container.textContent).toContain(fixture.request.id);
  state.readTarget=target;state.readStatus=403;
  const key=target==='history'?'customization-history':'buyer-brand-decision';
  await act(async()=>{await cache.invalidateQueries({queryKey:[key,'buyer']});});await settle();
  expect(container.textContent).not.toContain(fixture.request.id);
  expect(container.textContent).not.toContain(draft.watch_reference);
  expect(nodes(container).some(node=>node.tagName==='FORM')).toBe(false);
  expect(recall('buyer')).toBeNull();
  expect(cache.getQueryData(['customization-requests','buyer','draft',1])).toBeUndefined();
});

function activeForm() {
  return nodes(container).find(node=>node.tagName==='FORM'&&!hidden(node));
}
function hidden(node:TestNode):boolean {
  return 'hidden' in node.attributes || !!(node.parentNode&&hidden(node.parentNode));
}
async function navigate(query:string) {
  state.search=new URLSearchParams(query);
  window.location.href='https://example.test/en/custom-requests?'+query;
  await render();await settle();
}
it('opens deliberate configuration changes and restores the previous mounted editor on history navigation',async()=>{
  await mount();
  const first=activeForm();
  await navigate('configuration=second&revision=4');
  expect(activeForm()).not.toBe(first);
  expect(recall('buyer')?.form.configuration_id).toBe('second');
  expect(recall('buyer')?.form.configuration_revision).toBe(4);
  await navigate('configuration=config&revision=3');
  expect(activeForm()).toBe(first);
  expect(state.commands).toHaveLength(0);
});
it('opens a selected draft instead of reusing the previous record and revision',async()=>{
  await mount();
  await navigate('draft=second');
  const second=activeForm();
  expect(second?.textContent).toContain('second');
  expect(recall('buyer')?.id).toBe('second');
  await navigate('draft=third');
  expect(activeForm()).not.toBe(second);
  expect(recall('buyer')?.id).toBe('third');
  await navigate('draft=second');
  expect(activeForm()).toBe(second);
  expect(state.commands).toHaveLength(0);
});
it('retains the exact uncertain submission when navigating away and back to its draft',async()=>{
  await mount();
  const form=activeForm()!;
  await act(async()=>{(props(form).onSubmit as (event:{preventDefault:()=>void})=>void)({preventDefault:()=>{}});});await settle();
  await click('Review current dimensions');await click('Submit reviewed revision');
  const operation=state.commands[0];
  await navigate('configuration=second&revision=4');
  expect(activeForm()).not.toBe(form);
  await navigate('draft=draft');
  expect(activeForm()).toBe(form);
  await click('Reconcile the same submission');
  expect(state.commands).toHaveLength(2);
  expect(state.commands[1]).toEqual(operation);
});

it('reopens the retained pending submission from another configuration resume list',async()=>{
  await mount();
  const form=activeForm()!;
  await act(async()=>{(props(form).onSubmit as (event:{preventDefault:()=>void})=>void)({preventDefault:()=>{}});});await settle();
  await click('Review current dimensions');await click('Submit reviewed revision');
  const operation=state.commands[0];
  await navigate('configuration=second&revision=4');
  expect(activeForm()).not.toBe(form);
  await click(draft.watch_reference);
  expect(activeForm()).toBe(form);
  expect(new URL(window.location.href).searchParams.get('draft')).toBe('draft');
  await click('Reconcile the same submission');
  expect(state.commands).toHaveLength(2);
  expect(state.commands[1]).toEqual(operation);
});
