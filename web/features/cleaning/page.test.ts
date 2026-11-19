import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';
import fixtures from '../../../packages/contracts-service/cleaning/fixtures.json';
import contract from './delivery-contract.json';
const state=vi.hoisted(()=>({locale:'en' as 'en'|'ar'}));
vi.mock('next/navigation',()=>({useSearchParams:()=>new URLSearchParams('request=00000000-0000-4000-8000-000000000002')}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:'current'})}));
vi.mock('@/features/identity/session',()=>({useSession:()=>null,authenticatedRequest:vi.fn()}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:{record:{...fixtures.request,state:'requested',revision:1},quote:fixtures.quote,binding:fixtures.request},isPending:false,isError:false,refetch:vi.fn()})}));
import CleaningPage from '../../app/(cleaning)/care/cleaning/page';
import Cleaning from './view';
import { copy } from './copy';

it.each(['en','ar'] as const)('mounts the declared request and acceptance journey in %s',locale=>{
  state.locale=locale;
  const page=CleaningPage();
  expect(page.type).toBe(Cleaning);
  const html=renderToStaticMarkup(createElement(CleaningPage));
  expect(html).toContain(copy[locale].submit);
  expect(html).toContain(copy[locale].acceptedTerms);
  expect(html).toContain(copy[locale].accept);
  expect(html).toContain(`href="/${locale}/inbox"`);
  expect(html).toContain('aria-labelledby="page-title"');
  expect(html).toMatch(new RegExp(`id="page-title"[^>]*>${copy[locale].title}<`));
  expect(html).toContain(copy[locale].subject);
  expect(html).toContain(copy[locale].requested);
  expect(html).not.toContain('<main');
});
it('declares the owned route and shared-read view with proof still owed',()=>{
  expect(contract).toEqual({route:'/care/cleaning',file:'web/app/(cleaning)/care/cleaning/page.tsx',view:'web/features/cleaning/view.tsx',kind:'reads',reason:expect.any(String),content:'.bt-page',read:'cleaning.v1',proof:'owed'});
});
