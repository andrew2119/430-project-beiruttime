import { beforeEach, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { RecordView } from './api';
import en from './en.json';
import ar from './ar.json';
const state=vi.hoisted(()=>({locale:'en' as 'en'|'ar',signedIn:true,data:undefined as unknown}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/features/identity/session',()=>({useSession:()=>state.signedIn?{access_fingerprint:'synthetic'}:null,signInHref:()=>'/en/account?next=%2Fcare%2Fenlargement'}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:state.data,isPending:false,isError:false,refetch:vi.fn()})}));
import View from './view';
import { Actions, emptyActionDraft } from './actions';
beforeEach(()=>{state.locale='en';state.signedIn=true;state.data=undefined;});
it.each(['en','ar'] as const)('renders the canonical form and one heading in %s',locale=>{
  state.locale=locale;
  const html=renderToStaticMarkup(createElement(View));
  expect(html.match(/<h1\b/g)).toHaveLength(1);
  expect(html).toContain(locale==='ar'?ar.title:en.title);
  expect(html).toContain('bt-input');
  expect(html).not.toContain('<main');
  expect(html).not.toContain('undefined');
});
it.each(['en','ar'] as const)('denies anonymous request fields in %s',locale=>{
  state.locale=locale;state.signedIn=false;
  const html=renderToStaticMarkup(createElement(View));
  expect(html).toContain(locale==='ar'?ar.signin:en.signin);
  expect(html).not.toContain('<form');
});
it.each(['en','ar'] as const)('renders waiting and rework with actual context in %s',locale=>{
  state.locale=locale;
  state.data={state:'waiting',request_id:'synthetic',revision:1,next_review_at:'2026-11-18T00:00:00Z'};
  let html=renderToStaticMarkup(createElement(View));
  expect(html).toContain(locale==='ar'?ar.waiting:en.waiting);
  expect(html).toContain('2026-11-18T00:00:00Z');
  state.data={state:'rework',request_id:'synthetic',revision:2,responsible_operator_id:'operator-1',next_action:{en:'Correct fit',ar:'تصحيح الملاءمة'},next_review_at:'2026-11-18T00:00:00Z',first_response_due_at:'2026-11-18T00:00:00Z',escalation_at:'2026-11-19T00:00:00Z',quality:{fit:'قياس طويل mixed 👩🏽‍🔧'}};
  html=renderToStaticMarkup(createElement(View));
  expect(html).toContain(locale==='ar'?ar.rework:en.rework);
  expect(html).toContain('قياس طويل mixed 👩🏽‍🔧');
  for(const value of ['operator-1','2026-11-18T00:00:00Z','2026-11-19T00:00:00Z',locale==='ar'?'تصحيح الملاءمة':'Correct fit']) expect(html).toContain(value);
});
it('requires complete quote lines and terms before accepting',()=>{
  const record={state:'assessed',request_id:'synthetic',revision:2,allowed_operations:['accept']} as RecordView;
  const html=renderToStaticMarkup(createElement(Actions,{record,submitAction:vi.fn(),draft:emptyActionDraft(),onDraftChange:vi.fn()}));
  expect(html).toContain('disabled');
  expect(html).toContain(en.termsCheck);
});
it('keeps both dictionaries structurally complete',()=>{
  const keys=(value:unknown):string[]=>Object.entries(value as object).flatMap(([key,item])=>typeof item==='object'?keys(item).map(child=>`${key}.${child}`):[key]).sort();
  expect(keys(ar)).toEqual(keys(en));
});
it.each(['en','ar'] as const)('shows submitted measurement context to the assessor in %s',locale=>{
  state.locale=locale;
  state.data={state:'requested',request_id:'synthetic',revision:1,allowed_operations:['assess'],request:{measurement:'17.5',unit:'cm',measurement_mm:'175',method:'tape قياس',source:'Customer 👩🏽‍🔧',target:'Comfortable fit مريح',choice:'links'}};
  const html=renderToStaticMarkup(createElement(View));
  for(const value of ['17.5','175','tape قياس','Customer 👩🏽‍🔧','Comfortable fit مريح']) expect(html).toContain(value);
  expect(html).toContain(locale==='ar'?ar.requestContext:en.requestContext);
});
