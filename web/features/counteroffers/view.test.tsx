import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import { LocaleContext } from '@/shell/locale-context';
import View from './view';
import { currentCounter } from './model';
import type { Counter } from '@contracts/contracts-pricing/counteroffers';
import fixture from '../../../packages/contracts-pricing/counteroffers/fixtures/success.v1.json';
const state=vi.hoisted(()=>({counter:null as Counter|null,pending:false,error:false,cause:null as unknown}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:state.counter,isPending:state.pending,isError:state.error,error:state.cause,isSuccess:!state.pending&&!state.error,refetch:vi.fn()})}));
const noCommand=vi.fn(),lookup=vi.fn(),quote=vi.fn();
const terms={quote_id:fixture.current.economics.quote_id,quote_revision:1,terms_revision:1,
  en:{terms:'Retained sale terms',returns:'Controlled return conditions',assurance:'Private inspection conditions'},
  ar:{terms:'شروط البيع المحفوظة',returns:'شروط الإرجاع المنظم',assurance:'شروط الفحص الخاص'},support_href:'/support'};
function render(locale:'en'|'ar',withTerms=false) {
  return renderToStaticMarkup(<LocaleContext value={locale}><View terms={withTerms?terms:undefined} scope="private-scope" subjectId={fixture.current.subject_id} watchId={fixture.current.watch_id} actor={fixture.current.seller_id}
    sourceRevision={3} authorityRevision={2} read={null} send={noCommand} lookup={lookup} quote={quote}/></LocaleContext>);
}
describe('counteroffer presentation',()=>{
  it('renders exact economics and controlled input in both languages without a command',()=>{
    state.counter=fixture.current as Counter;
    for(const locale of ['en','ar'] as const){
      const html=render(locale);
      expect(html).toContain('counter-price');expect(html).toContain('USD');
      expect(html).toContain(locale==='en'?'Buyer total':'إجمالي المشتري');
      expect(html).toContain(locale==='en'?'5,150.00':'٥٬١٥٠٫٠٠');
      expect(html).not.toContain('undefined');
    }
    expect(noCommand).not.toHaveBeenCalled();expect(quote).not.toHaveBeenCalled();
  });
  it('keeps the form identity independent of locale and retains operation state in memory',()=>{
    const source=readFileSync(new URL('./view.tsx',import.meta.url),'utf8');
    expect(source).toContain('key={JSON.stringify([props.scope,props.subjectId,props.watchId,props.actor])}');
    expect(source).not.toMatch(/key=\{[^}]*locale/);
    expect(source).not.toMatch(/localStorage|sessionStorage|document.cookie/);
    expect(source).toContain('replay?send(operation):lookup(operation)');
  });
  it('shows empty recovery in both languages',()=>{
    state.counter=null;
    expect(render('en')).toContain('No current counteroffer.');
    expect(render('ar')).toContain('لا يوجد عرض مقابل حالي.');
  });
});

it('suppresses retained private economics and actions on a denied refresh in both languages',()=>{
  state.counter=fixture.current as Counter;state.error=true;state.cause={status:403};
  for(const locale of ['en','ar'] as const){
    const html=render(locale);
    expect(html).toContain(locale==='en'?'Access denied':'الوصول مرفوض');
    expect(html).not.toContain('counter-price');
    expect(html).not.toContain(fixture.current.expires_at);
    expect(html).not.toContain(locale==='en'?'Buyer total':'إجمالي المشتري');
  }
  state.error=false;state.cause=null;
});
it('requires bound terms before the review control becomes available',()=>{
  state.counter=fixture.current as Counter;
  expect(render('en')).toContain('Exact terms are unavailable.');
  expect(render('ar')).toContain('الشروط الدقيقة غير متاحة.');
});

it('shows complete bound terms and support in both languages',()=>{
  state.counter=fixture.current as Counter;
  for(const locale of ['en','ar'] as const){
    const html=render(locale,true);
    for(const text of Object.values(terms[locale]))expect(html).toContain(text);
    expect(html).toContain('href="/support"');
    expect(html).not.toContain(locale==='en'?'Exact terms are unavailable.':'الشروط الدقيقة غير متاحة.');
  }
});
it('applies closed command state over retained sent data and never regresses a newer read',()=>{
  const sent=fixture.current as Counter;
  const closed={...sent,state:'closed' as const,revision:sent.revision+1};
  expect(currentCounter(sent,closed,false,sent.subject_id,sent.watch_id)).toBe(closed);
  expect(currentCounter({...sent,revision:closed.revision+1},closed,false,sent.subject_id,sent.watch_id)?.revision).toBe(closed.revision+1);
  expect(currentCounter(sent,closed,true,sent.subject_id,sent.watch_id)).toBeNull();
  state.counter=closed;
  const html=render('en',true);
  expect(html).toContain('This counteroffer is closed.');
  expect(html).not.toContain('Response recorded.');
});
