import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';
const state = vi.hoisted(()=>({locale:'en' as 'en'|'ar',status:'authenticated',data:undefined as unknown,error:null as unknown}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/features/identity/session',()=>({useSession:()=>null,useSessionState:()=>state.status,refreshSession:vi.fn()}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:vi.fn(()=>({data:state.data,isError:!!state.error,error:state.error,isPending:false,isFetching:false,refetch:vi.fn()}))}));
vi.mock('@/lib/page-speed/arrival',()=>({AnswerArrival:({children}:{children:unknown})=>children}));
vi.mock('./api',()=>({operationRead:vi.fn(),releaseRead:vi.fn(),submit:vi.fn(),recover:vi.fn()}));
import PayoutsUnavailable, { ReleaseDesk } from './view';
import { COPY } from './copy';
it.each(['en','ar'] as const)('renders honest unavailable and empty recovery in %s',locale=>{
  state.locale=locale;
  const html=renderToStaticMarkup(createElement(PayoutsUnavailable));
  expect(html).toContain(COPY[locale].unavailable);
  expect(html).toContain(COPY[locale].support);
  expect(html).not.toContain('<main');
  const desk=renderToStaticMarkup(createElement(ReleaseDesk,{actor:'x',organization:null,fingerprint:'current'}));
  expect(desk).toContain(COPY[locale].emptyBody);
  expect(desk).toContain(COPY[locale].order);
  expect(desk).not.toContain('localStorage');
});

it('shows an existing transfer recovery reference after reopening',async()=>{
  const { readFileSync } = await import('node:fs');
  const fixture = JSON.parse(readFileSync(new URL('../../../packages/contracts-orders/releases/fixtures.json',import.meta.url),'utf8'));
  // First read supplies the current order, the second supplies its durable operation.
  const reads = await import('@/lib/page-speed/read');
  let count = 0;
  vi.mocked(reads.usePageRead).mockImplementation((() => ({
    data:count++ === 0 ? {snapshot:{...fixture.source,active_release_operation_id:fixture.command.operation_id},missing:['release_exists'],closes_at:fixture.now,simulated:true} : fixture.transfer_pending,
    isError:false,isPending:false,isFetching:false,refetch:vi.fn(),
  })) as unknown as typeof reads.usePageRead);
  const html=renderToStaticMarkup(createElement(ReleaseDesk,{actor:fixture.command.actor_id,organization:null,fingerprint:'current'}));
  expect(html).toContain(fixture.command.operation_id);
  expect(html).toContain(COPY[state.locale].recover);
  expect(html).not.toContain(COPY[state.locale].release);
});
