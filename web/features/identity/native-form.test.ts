import { beforeEach, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { Session } from '@contracts/contracts-identity/accounts';
const owner = vi.hoisted(()=>({ session:null as Session|null,locale:'en' as 'en'|'ar' }));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>owner.locale}));
vi.mock('next/navigation',()=>({useRouter:()=>({push:vi.fn()})}));
vi.mock('next/link',()=>({default:'a'}));
vi.mock('@tanstack/react-query',()=>({
  useQueryClient:()=>({setQueryData:vi.fn(),invalidateQueries:vi.fn()}),
  useQuery:()=>({data:{application:null,consents:[]},isPending:false,error:null})
}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:undefined,error:null,refetch:vi.fn()})}));
vi.mock('@/lib/page-speed/arrival',()=>({AnswerArrival:({children}:{children:unknown})=>children}));
vi.mock('./session',()=>({
  useSession:()=>owner.session,useSessionState:()=>owner.session?'authenticated':'signed-out',
  accountApi:'/api/web/v1/identity/v1/accounts',beginSession:vi.fn(),authenticatedRequest:vi.fn(),
  refreshSession:vi.fn(),signOut:vi.fn(),safeReturnPath:(value:string)=>value,
  signInHref:()=>'/en/account'
}));
import AccountView from './account-view';
import SellerView, { SellerApplicationForm } from './seller-view';
import ConsentView from '../consent/consent-view';
const sample:Session={access_token:'memory-only',token_type:'Bearer',expires_in:300,account:{id:'sample',email:'demo@example.test',display_name:'Demo'},principal:{actor:{subject_id:'sample',session_id:'lineage',organization_id:null},roles:['buyer'],permissions:[],organizations:[],organization_grants:[]},access_fingerprint:'one-way-scope'};
beforeEach(()=>{owner.session=null;owner.locale='en';});
function expectPrivateFormsPost(html:string) {
  const forms=[...html.matchAll(/<form\b([^>]*)>/g)];
  expect(forms.length).toBeGreaterThan(0);
  for(const form of forms)expect(form[1]).toContain('method="post"');
}
it.each(['signin','register','recovery','reset'] as const)('keeps %s secrets out of native GET URLs before hydration',mode=>{
  expectPrivateFormsPost(renderToStaticMarkup(createElement(AccountView,{initialMode:mode})));
});
it('uses POST for password-change fallback',()=>{
  owner.session=sample;expectPrivateFormsPost(renderToStaticMarkup(createElement(AccountView)));
});
it('uses POST for private seller evidence fallback',()=>{
  owner.session=sample;expectPrivateFormsPost(renderToStaticMarkup(createElement(SellerApplicationForm,{pending:false,onSubmit:vi.fn()})));
  const shell=renderToStaticMarkup(createElement(SellerView));
  expect(shell).toContain('aria-busy="true"');
});
it('uses POST for private consent fallback',()=>{
  owner.session=sample;expectPrivateFormsPost(renderToStaticMarkup(createElement(ConsentView)));
});

it.each(['en','ar'] as const)('renders the same account field names in %s',locale=>{
  owner.locale=locale;
  for(const mode of ['signin','register','recovery','reset'] as const) {
    const html=renderToStaticMarkup(createElement(AccountView,{initialMode:mode}));
    expectPrivateFormsPost(html);
    expect(html).toContain('bt-page-header');
    if(mode!=='recovery') expect(html).toContain('name="password"');
    if(mode!=='reset') expect(html).toContain('name="email"');
    expect(html).not.toContain('name="locale"');
  }
});

 it.each(['en','ar'] as const)('exposes native submit activation in %s', locale=>{
  owner.locale=locale;
  const pages = (['signin','register','recovery','reset'] as const).map(initialMode=>renderToStaticMarkup(createElement(AccountView,{initialMode})));
  owner.session=sample;
  pages.push(renderToStaticMarkup(createElement(AccountView)));
  pages.push(renderToStaticMarkup(createElement(SellerApplicationForm,{pending:false,onSubmit:vi.fn()})));
  for(const html of pages) {
    for(const form of html.matchAll(/<form\b[^>]*>([\s\S]*?)<\/form>/g)) {
      expect(form[1]).toMatch(/<button[^>]*type="submit"/);
    }
  }
});
