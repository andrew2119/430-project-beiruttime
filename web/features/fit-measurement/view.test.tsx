import type { FitContext } from '@contracts/contracts-service/fit-measurement/v1';
import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, expect, it, vi } from 'vitest';
const state=vi.hoisted(()=>({locale:'en' as 'en'|'ar', retained:undefined as FitContext|undefined}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/features/identity/session',()=>({useSession:()=>null,useSessionState:()=> 'signed-out',refreshSession:vi.fn(),authenticatedRequest:vi.fn()}));
vi.mock('@/lib/page-speed/read',async importOriginal=>{
  const original=await importOriginal<typeof import('@/lib/page-speed/read')>();
  return {...original,usePageRead:(...args:Parameters<typeof original.usePageRead>)=>state.retained?{data:state.retained,isFetching:true,isError:false,error:null,refetch:vi.fn()}:original.usePageRead(...args)};
});
afterEach(()=>{state.retained=undefined;});
import { MeasurementForm } from './view';
import { PageReadProvider } from '@/lib/page-speed/provider';
import { copy } from './copy';
const scope={subject_id:'',watch_id:'',organization_id:''};
it.each(['en','ar'] as const)('renders localized scope recovery with one page frame: %s',locale=>{
  state.locale=locale;
  const html=renderToStaticMarkup(<MeasurementForm scope={scope} access="current" sessionState="authenticated"/>);
  expect(html).toContain(copy[locale].title);
  expect(html).toContain(copy[locale].scope);
  expect(html).not.toContain('<main');
});
it('distinguishes unavailable identity from denied access',()=>{
  state.locale='en';
  const html=renderToStaticMarkup(<MeasurementForm scope={scope} access={null} sessionState="unavailable"/>);
  expect(html).toContain(copy.en.unavailable);
  expect(html).toContain(copy.en.reload);
  expect(html).not.toContain(copy.en.denied);
});

it.each(['en','ar'] as const)('renders page failure recovery without private content: %s',async locale=>{
  state.locale=locale;
  const {default:FitError}=await import('../../app/(fit-measurement)/care/fit/error');
  const html=renderToStaticMarkup(createElement(FitError,{reset:vi.fn()}));
  expect(html).toContain(copy[locale].unavailable);
  expect(html).toContain(copy[locale].reload);
  expect(html).not.toContain('<main');
  expect(html).not.toContain('175');
});

it.each(['en','ar'] as const)('renders selected-record loading within the shared read scope: %s',locale=>{
  state.locale=locale;
  const selected={subject_id:'00000000-0000-4000-8000-000000000001',watch_id:'00000000-0000-4000-8000-000000000003',organization_id:'00000000-0000-4000-8000-000000000004'};
  const html=renderToStaticMarkup(<PageReadProvider><MeasurementForm scope={selected} access="current" sessionState="authenticated"/></PageReadProvider>);
  expect(html).toContain(copy[locale].loading);
  expect(html).not.toContain('<main');
});

it.each(['en','ar'] as const)('keeps a retained answer visible with saves disabled during unresolved refresh: %s',locale=>{
  state.locale=locale;
  const fixture=JSON.parse(readFileSync(new URL('../../../packages/contracts-service/fit-measurement/fixtures.json',import.meta.url),'utf8'));
  const selected={subject_id:fixture.record.subject_id,watch_id:fixture.record.watch_id,organization_id:fixture.record.organization_id};
  state.retained={...selected,source_revision:1,record:fixture.record};
  const html=renderToStaticMarkup(<PageReadProvider><MeasurementForm scope={selected} access="current" sessionState="authenticated"/></PageReadProvider>);
  expect(html).toContain(copy[locale].recorded);
  expect(html).toContain(locale==='ar'?'١٧٥':'175');
  expect(html).toContain(copy[locale].comfortable);
  expect(html).not.toContain(copy[locale].loading);
  expect(html).toMatch(/<input[^>]*disabled=""/);
  expect(html).toMatch(/<button[^>]*type="submit"[^>]*disabled=""/);
});
