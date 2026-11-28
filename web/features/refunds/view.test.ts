import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, expect, it, vi } from 'vitest';
const state=vi.hoisted(()=>({locale:'en',session:true,pending:false,error:null as unknown,
  data:undefined as undefined|{binding:Record<string,unknown>;remaining_minor:number}}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/features/identity/session',()=>({useSession:()=>state.session?{access_fingerprint:'scope'}:null}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:state.data,error:state.error,
  isPending:state.pending,isFetching:false,refetch:vi.fn()})}));
import RefundView from './view';
import { copy } from './copy';
import { RefundFailure } from './model';
beforeEach(()=>{state.locale='en';state.session=true;state.pending=false;state.error=null;state.data=undefined;});
it.each(['en','ar'] as const)('renders sign-in, loading, denied, unavailable and empty in %s',locale=>{
  state.locale=locale;const t=copy[locale];
  const render=()=>renderToStaticMarkup(createElement(RefundView));
  state.session=false;expect(render()).toContain(t.signIn);
  state.session=true;state.pending=true;expect(render()).toContain(t.loading);
  state.pending=false;state.error=new RefundFailure('denied');expect(render()).toContain(t.denied);
  state.error=new Error();expect(render()).toContain(t.unavailable);
  state.error=null;state.data={binding:{},remaining_minor:0};expect(render()).toContain(t.empty);
});
it.each(['en','ar'] as const)('renders the same labeled dollar form in %s',locale=>{
  state.locale=locale;state.data={binding:{},remaining_minor:500000};
  const html=renderToStaticMarkup(createElement(RefundView));
  expect(html).toContain(copy[locale].amount);
  expect(html).toContain('inputMode="decimal"');
  expect(html).toContain(copy[locale].submit);
  expect(html).not.toContain('<main');
});

it.each(['en','ar'] as const)('hides a retained answer after a denied refresh in %s',locale=>{
  state.locale=locale;state.data={binding:{},remaining_minor:500000};
  const render=()=>renderToStaticMarkup(createElement(RefundView));
  expect(render()).toContain(copy[locale].remaining);
  state.error=new RefundFailure('denied');
  const denied=render();
  expect(denied).toContain(copy[locale].denied);
  expect(denied).toContain(copy[locale].load);
  for (const privateText of [copy[locale].remaining,copy[locale].lastKnown,
    copy[locale].amount,copy[locale].reference,copy[locale].review,copy[locale].lookup]) {
    expect(denied).not.toContain(privateText);
  }
  expect(denied).not.toContain('<form');
  expect(denied).not.toContain('<input');
});
