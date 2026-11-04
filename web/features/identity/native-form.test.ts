import { beforeEach, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { Session } from '@contracts/contracts-identity/accounts';
const owner = vi.hoisted(()=>({ session:null as Session|null }));
vi.mock('next/navigation',()=>({useRouter:()=>({push:vi.fn()})}));
vi.mock('next/link',()=>({default:'a'}));
vi.mock('@tanstack/react-query',()=>({
  useQueryClient:()=>({setQueryData:vi.fn(),invalidateQueries:vi.fn()}),
  useQuery:()=>({data:{application:null,consents:[]},isPending:false,error:null})
}));
vi.mock('./session',()=>({
  useSession:()=>owner.session,useSessionState:()=>owner.session?'authenticated':'signed-out',
  accountApi:'/api/web/v1/identity/v1/accounts',beginSession:vi.fn(),authenticatedRequest:vi.fn(),
  refreshSession:vi.fn(),signOut:vi.fn(),safeReturnPath:(value:string)=>value,
  signInHref:()=>'/en/account'
}));
import AccountView from './account-view';
import SellerView from './seller-view';
import ConsentView from '../consent/consent-view';
const sample:Session={access_token:'memory-only',token_type:'Bearer',expires_in:300,account:{id:'sample',email:'demo@example.test',display_name:'Demo'},principal:{actor:{subject_id:'sample',session_id:'lineage',organization_id:null},roles:['buyer'],permissions:[],organizations:[],organization_grants:[]},access_fingerprint:'one-way-scope'};
beforeEach(()=>{owner.session=null;});
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
  owner.session=sample;expectPrivateFormsPost(renderToStaticMarkup(createElement(SellerView)));
});
it('uses POST for private consent fallback',()=>{
  owner.session=sample;expectPrivateFormsPost(renderToStaticMarkup(createElement(ConsentView)));
});
