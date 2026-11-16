import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, expect, it, vi } from 'vitest';
import type { Session } from '@contracts/contracts-identity/accounts';
import AuctionStudio from './studio';
import en from './en.json';
import ar from './ar.json';
const state=vi.hoisted(()=>({locale:'en' as 'en'|'ar',session:null as Session|null,status:'signed-out',selectOptions:[] as string[]}));
// Select mounts its menu on engagement. Check its authorized options directly.
vi.mock('@beirut-time/ui',async importOriginal=>({
  ...await importOriginal<typeof import('@beirut-time/ui')>(),
  Select:({options,value}:{options:{value:string;label:string}[];value:string})=>{
    state.selectOptions.push(...options.map(option=>option.value));
    return createElement('button',{type:'button'},options.find(option=>option.value===value)?.label);
  },
}));
vi.mock('@/features/identity/session',()=>({useSession:()=>state.session,useSessionState:()=>state.status,refreshSession:vi.fn(),authenticatedRequest:vi.fn(),signInHref:()=>'/en/account?next=%2Fseller%2Fauctions'}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/shell/private-state',()=>({readNonSecretDraft:()=>null,saveNonSecretDraft:vi.fn()}));
beforeEach(()=>{state.locale='en';state.status='signed-out';state.session=null;state.selectOptions=[];});
function render(){return renderToStaticMarkup(createElement(QueryClientProvider,{client:new QueryClient()},createElement(AuctionStudio)));}
function signedIn(permissions:string[]=[]):Session {
  return {access_token:'test-only',token_type:'Bearer',expires_in:300,access_fingerprint:'test-owner',
    account:{id:'test-buyer',email:'sample@example.test',display_name:'Sample buyer'},
    principal:{actor:{subject_id:'test-buyer',session_id:'test-session',organization_id:null},roles:['buyer'],permissions,organizations:[],organization_grants:[]}};
}
it.each(['en','ar'] as const)('renders %s seller controls only with the canonical grant',locale=>{
  state.locale=locale;state.status='authenticated';state.session=signedIn(['identity.listings.publish']);
  const html=render(),copy=locale==='ar'?ar:en;
  expect(html).toContain(copy.title);expect(html).toContain(copy.addBand);expect(html).toContain(copy.reserve);
  expect(html).toContain('datetime-local');expect(html).toContain('<form');expect(html).not.toContain('LBP');expect(state.selectOptions).not.toContain('LBP');
});
it.each(['en','ar'] as const)('does not grant %s seller controls to a buyer',locale=>{
  state.locale=locale;state.status='authenticated';state.session=signedIn();
  const html=render();expect(html).toContain((locale==='ar'?ar:en).denied);expect(html).not.toContain('<form');
});
it('keeps restoring distinct from signed-out',()=>{
  state.status='restoring';const html=render();expect(html).toContain(en.restoringSession);expect(html).not.toContain('?next=');
});
it('shows explicit retry, not invented sign-out, on unavailable Identity',()=>{
  state.status='unavailable';const html=render();expect(html).toContain(en.unavailable);expect(html).toContain(en.retry);expect(html).not.toContain('?next=');
});
it('preserves the owned sign-in return when actually signed out',()=>{
  expect(render()).toContain('/en/account?next=%2Fseller%2Fauctions');
});
it('offers only exact held organization publishing grants',()=>{
  state.status='authenticated';state.session=signedIn();state.session.principal.organization_grants=[
    {organization_id:'sample-business-publisher',roles:['business'],permissions:['identity.listings.publish']},
    {organization_id:'sample-business-reader',roles:['business'],permissions:['business.records.read']},
  ];
  const html=render();expect(state.selectOptions).toContain('sample-business-publisher');expect(state.selectOptions).not.toContain('sample-business-reader');expect(html).not.toContain('<form');
});
