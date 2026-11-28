import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, expect, it, vi } from 'vitest';
import fixtures from '../../../packages/contracts-service/cleaning/fixtures.json';
const state=vi.hoisted(()=>({locale:'en' as 'en'|'ar',access:'current',data:{} as Record<string,unknown>,pending:false,error:false,readError:null as unknown}));
vi.mock('next/navigation',()=>({useSearchParams:()=>new URLSearchParams('request=00000000-0000-4000-8000-000000000002')}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:state.access})}));
vi.mock('@/features/identity/session',()=>({useSession:()=>null,authenticatedRequest:vi.fn()}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:state.data,isPending:state.pending,isError:state.error,error:state.readError,refetch:vi.fn()})}));
import Cleaning from './view';
import { copy } from './copy';
import { ApiError } from '@/lib/api/client';
const render=()=>renderToStaticMarkup(createElement(Cleaning));
beforeEach(()=>{state.locale='en';state.access='current';state.data={record:null,quote:null,binding:fixtures.request};state.pending=false;state.error=false;state.readError=null;});
it.each(['en','ar'] as const)('renders explicit limits, empty and recovery in %s',locale=>{
  state.locale=locale;
  const html=render();
  expect(html).toContain(copy[locale].intro);
  expect(html).toContain(copy[locale].empty);
  expect(html).toContain(copy[locale].water);
  expect(html).toContain(copy[locale].movement);
  for(const label of [copy[locale].subject,copy[locale].condition,copy[locale].limits]) {
    expect(html).toContain(label);
  }
  expect(html).not.toContain('<main');
});
it.each(['en','ar'] as const)('renders retained quote and condition in %s',locale=>{
  state.locale=locale;
  state.data={record:{...fixtures.request,state:'accepted',revision:2,quote:fixtures.quote},quote:null};
  const html=render();
  expect(html).toContain(copy[locale].accepted);
  expect(html).toContain(fixtures.quote.process);
  expect(html).toContain(fixtures.quote.condition);
  expect(html).toContain(fixtures.quote.terms);
  expect(html).not.toContain(copy[locale].acceptedTerms);
});
it('keeps long mixed notes as text, never markup',()=>{
  const text='ساعة ABC 🕰️ <script>private</script> '.repeat(50);
  state.data={record:{...fixtures.request,state:'requested',areas:['bracelet'],condition:text,preservation_limits:text},quote:fixtures.quote};
  const html=render();
  expect(html).toContain('&lt;script&gt;');
  expect(html).not.toContain('<script>private');
});
it('renders unavailable and loading without guessed success',()=>{
  state.pending=true;expect(render()).toContain(copy.en.loading);
  state.pending=false;state.error=true;expect(render()).toContain(copy.en.unavailable);
  expect(render()).not.toContain(copy.en.accepted);
});
it('clears private content when access is absent',()=>{
  state.access='';state.data={record:{condition:'private condition'},quote:fixtures.quote};
  const html=render();expect(html).toContain(copy.en.signedOut);expect(html).not.toContain('private condition');
});

it('hides retained private facts on a current permission denial',()=>{
  state.error=true;state.readError=new ApiError(403,'denied','');
  state.data={record:{...fixtures.request,condition:'restricted condition'},quote:fixtures.quote};
  const html=render();expect(html).toContain(copy.en.denied);expect(html).not.toContain('restricted condition');expect(html).not.toContain(fixtures.quote.process);
});

it.each(['en','ar'] as const)('renders native submit controls and localized support before acceptance in %s',locale=>{
  state.locale=locale;
  state.data={record:{...fixtures.request,state:'requested',revision:1},quote:fixtures.quote,binding:fixtures.request};
  const html=render();
  const buttons=[...html.matchAll(/<button\b([^>]*)>(.*?)<\/button>/g)];
  for(const label of [copy[locale].open,copy[locale].submit]) {
    expect(buttons.find(([, , text])=>text.replace(/<[^>]*>/g,'')===label)?.[1]).toContain('type="submit"');
  }
  expect(html).toContain(`href="/${locale}/inbox"`);
  expect(html.indexOf(copy[locale].support)).toBeLessThan(html.indexOf(copy[locale].acceptedTerms));
});
