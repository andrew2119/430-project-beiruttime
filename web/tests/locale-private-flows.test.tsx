import { afterEach, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import Checkout from '../features/buy-now/checkout';
import RequestDrafts from '../features/request-drafts/request-drafts';
import { LocaleControl } from '../shell/foundation/locale-control';
import { Button } from '@beirut-time/ui/foundation';
import { recallReservation, rememberReservation, purgeReservation, reservationMemoryEpoch } from '../features/buy-now/memory';
import { recall, remember, purge, draftMemoryEpoch } from '../features/request-drafts/memory';

const state=vi.hoisted(() => ({effects:[] as (() => unknown)[], change:vi.fn(), save:vi.fn(), reserve:vi.fn()}));
vi.mock('react', async () => ({...await vi.importActual('react'),
  useState:(initial:unknown) => [typeof initial==='function' ? initial() : initial, vi.fn()],
  useRef:(value:unknown) => ({current:value}), useCallback:(callback:unknown) => callback,
  useEffect:(effect:() => unknown) => {state.effects.push(effect);},
}));
vi.mock('@tanstack/react-query', () => ({useQuery:({queryKey}:{queryKey:string[]}) => ({data:['l08-orders','l08-drafts'].includes(queryKey[0]) ? {items:[]} : undefined}),useInfiniteQuery:({queryKey}:{queryKey:string[]}) => ({data:{pages:queryKey[0]==='l08-drafts' ? [{items:[],total:0,next_cursor:null}] : []}}),useQueryClient:() => ({invalidateQueries:vi.fn()})}));
vi.mock('../shell/locale-context', () => ({useLocale:() => 'en',useLocaleChange:() => state.change}));
vi.mock('next/navigation', () => ({useRouter:() => ({refresh:vi.fn()}),useSearchParams:() => new URLSearchParams()}));
vi.mock('@/features/identity/session', () => ({useSession:() => ({access_fingerprint:'owner',principal:{actor:{subject_id:'buyer'}}}),signInHref:() => '/en/account'}));
vi.mock('../features/request-drafts/api', () => ({draftApi:{save:state.save}}));
vi.mock('../features/buy-now/api', () => ({buyNowApi:{reserve:state.reserve}}));
afterEach(() => {state.effects=[];purge();purgeReservation();vi.clearAllMocks();vi.unstubAllGlobals();});

it.each(['dirty draft','uncertain reservation'])('%s does not write or navigate when the header language changes', flow => {
  const listeners:((event:unknown) => void)[]=[];
  const navigate=vi.fn();
  class Target {
    closest(selector:string) { return selector==='a.locale-control' && control.type==='a' ? this : null; }
  }
  vi.stubGlobal('Element',Target);
  vi.stubGlobal('window',{addEventListener:vi.fn(),location:{href:'https://example.test/en/checkout?q=retained#step',assign:navigate}});
  vi.stubGlobal('document',{addEventListener:(name:string,run:(event:unknown) => void) => {if(name==='click') listeners.push(run);}});
  const pending={body:{watch_id:'watch',quote_id:'quote',expected_revision:1},key:'operation-17'};
  rememberReservation({owner:'owner',watch:'watch',quote:'quote',checked:'watch',pending},reservationMemoryEpoch());
  const form={configuration_id:null,configuration_revision:null,brand_id:null,kind:'customization' as const,watch_context:'undecided' as const,watch_reference:'',scope_intent:'scope',notes:'نور ⌚',options:{}};
  remember({owner:'owner',id:null,revision:0,form,dirty:true,pending:null},draftMemoryEpoch());
  const draft=recall('owner'), reservation=recallReservation('owner');
  // Render the actual private components so their nested hooks have a dispatcher.
  renderToStaticMarkup(flow==='dirty draft' ? createElement(RequestDrafts) : createElement(Checkout, {}));
  for(const effect of state.effects) effect();
  // The current checkout no longer installs a legacy locale-link listener.
  expect(listeners).toHaveLength(flow==='dirty draft' ? 1 : 0);
  const control=LocaleControl({});
  expect(control.type).toBe(Button);
  const event={target:new Target(),button:0,preventDefault:vi.fn(),stopPropagation:vi.fn()};
  for(const listener of listeners) listener(event);
  control.props.onClick();
  expect(state.change).toHaveBeenCalledWith('ar');
  expect(event.preventDefault).not.toHaveBeenCalled();
  expect(state.save).not.toHaveBeenCalled();
  expect(state.reserve).not.toHaveBeenCalled();
  expect(navigate).not.toHaveBeenCalled();
  expect(recall('owner')).toEqual(draft);
  expect(recallReservation('owner')?.pending).toBe(reservation?.pending);
});
