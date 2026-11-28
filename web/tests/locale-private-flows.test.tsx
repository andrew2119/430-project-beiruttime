import { afterEach, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import Checkout from '../features/buy-now/checkout';
import RequestDrafts from '../features/request-drafts/request-drafts';
import { LocaleControl } from '../shell/foundation/locale-control';
import { Button } from '@beirut-time/ui/foundation';
import { connectedCopy } from '../features/buy-now/connected-copy';
import { recall, remember, purge, draftMemoryEpoch } from '../features/request-drafts/memory';
import { readNonSecretDraft, saveNonSecretDraft, setAccessContext } from '../shell/private-state';

const state=vi.hoisted(() => ({
  effects:[] as (() => unknown)[], locale:'en' as 'en' | 'ar', change:vi.fn(), save:vi.fn(), request:vi.fn(),
}));
vi.mock('react', async () => ({...await vi.importActual('react'),
  useState:(initial:unknown) => [typeof initial==='function' ? initial() : initial, vi.fn()],
  useRef:(value:unknown) => ({current:value}), useCallback:(callback:unknown) => callback,
  useEffect:(effect:() => unknown) => {state.effects.push(effect);},
}));
vi.mock('@tanstack/react-query', () => ({useQuery:({queryKey}:{queryKey:string[]}) => ({data:['l08-orders','l08-drafts'].includes(queryKey[0]) ? {items:[]} : undefined}),useInfiniteQuery:({queryKey}:{queryKey:string[]}) => ({data:{pages:queryKey[0]==='l08-drafts' ? [{items:[],total:0,next_cursor:null}] : []}}),useQueryClient:() => ({invalidateQueries:vi.fn()})}));
vi.mock('../shell/locale-context', () => ({useLocale:() => state.locale,useLocaleChange:() => state.change}));
vi.mock('next/navigation', () => ({useRouter:() => ({refresh:vi.fn()}),useSearchParams:() => new URLSearchParams()}));
vi.mock('@/features/identity/session', () => ({authenticatedRequest:state.request,useSession:() => ({access_fingerprint:'owner',principal:{actor:{subject_id:'buyer'}}}),signInHref:() => '/en/account'}));
vi.mock('../features/request-drafts/api', () => ({draftApi:{save:state.save}}));
vi.mock('../features/buy-now/api', () => ({buyNowApi:{orders:state.request,availability:state.request}}));
afterEach(() => {setAccessContext(null);state.effects=[];state.locale='en';purge();vi.clearAllMocks();vi.unstubAllGlobals();});

it.each(['dirty draft','uncertain reservation'])('%s does not write or navigate when the header language changes', flow => {
  const listeners:((event:unknown) => void)[]=[];
  const navigate=vi.fn();
  class Target {
    closest(selector:string) { return selector==='a.locale-control' && control.type==='a' ? this : null; }
  }
  vi.stubGlobal('Element',Target);
  vi.stubGlobal('window',{addEventListener:vi.fn(),dispatchEvent:vi.fn(),location:{href:'https://example.test/en/checkout?q=retained#step',assign:navigate}});
  vi.stubGlobal('document',{addEventListener:(name:string,run:(event:unknown) => void) => {if(name==='click') listeners.push(run);}});
  const storage=new Map<string,string>();
  const saveDraft=vi.fn((key:string,value:string) => storage.set(key,value));
  vi.stubGlobal('sessionStorage',{
    get length() { return storage.size; },
    key:(index:number) => [...storage.keys()][index] ?? null,
    getItem:(key:string) => storage.get(key) ?? null,
    removeItem:(key:string) => storage.delete(key),
    setItem:saveDraft,
  });
  setAccessContext('owner');
  const pending={owner:'owner',listingId:'listing',watch:'watch',quote:'quote',
    body:{watch_id:'watch',quote_id:'quote',expected_revision:1},key:'operation-17'};
  saveNonSecretDraft('owner','checkout-operation',JSON.stringify(pending));
  saveDraft.mockClear();
  const form={configuration_id:null,configuration_revision:null,brand_id:null,kind:'customization' as const,watch_context:'undecided' as const,watch_reference:'',scope_intent:'scope',notes:'نور ⌚',options:{}};
  remember({owner:'owner',id:null,revision:0,form,dirty:true,pending:null},draftMemoryEpoch());
  const renderFlow=() => renderToStaticMarkup(flow==='dirty draft' ? createElement(RequestDrafts) : createElement(Checkout, {}));
  const before=renderFlow();
  for(const effect of state.effects) effect();
  expect(listeners).toHaveLength(flow==='dirty draft' ? 1 : 0);
  if(flow==='uncertain reservation') expect(before).toContain(connectedCopy.en.retry);
  const control=LocaleControl({});
  expect(control.type).toBe(Button);
  const event={target:new Target(),button:0,preventDefault:vi.fn(),stopPropagation:vi.fn()};
  for(const listener of listeners) listener(event);
  control.props.onClick();
  expect(state.change).toHaveBeenCalledWith('ar');
  state.locale='ar';
  if(flow==='uncertain reservation') expect(renderFlow()).toContain(connectedCopy.ar.retry);
  expect(event.preventDefault).not.toHaveBeenCalled();
  expect(state.save).not.toHaveBeenCalled();
  expect(state.request).not.toHaveBeenCalled();
  expect(saveDraft).not.toHaveBeenCalled();
  expect(navigate).not.toHaveBeenCalled();
  expect(recall('owner')).toMatchObject({owner:'owner',id:null,form,dirty:true,pending:null});
  expect(JSON.parse(readNonSecretDraft('owner','checkout-operation') ?? 'null')).toEqual(pending);
});
