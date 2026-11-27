import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const state = vi.hoisted(()=>({locale:'en' as 'en'|'ar', session:true, error:null as unknown, historyError:null as unknown, total:0}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/features/identity/session',()=>({useSession:()=>state.session?{access_fingerprint:'synthetic-access'}:null,authenticatedRequest:vi.fn()}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:(read:{key:unknown[]})=>read.key[0]==='private-review-v1'?{
  isPending:false,error:state.error,data:{case_id:'synthetic-case',assignment_revision:1,revision:1,state:'under_review',binding:{source_revision:1}},refetch:vi.fn(),
}:{isPending:false,error:state.historyError,data:{items:state.total?[{operation_id:'synthetic-operation',verdict:'correction',reason:'اسم طويل Mixed العربية ⌚',review_revision:1}]:[],total:state.total,page:1,page_size:25},refetch:vi.fn()}}));
import ReviewView from '../../../../web/features/eligibility-review/view';
import { ApiError } from '../../../../web/lib/api/client';
import { copy } from '../../../../web/features/eligibility-review/copy';

describe('assigned review rendering',()=>{
  beforeEach(()=>{state.locale='en';state.session=true;state.error=null;state.historyError=null;state.total=0;});
  it.each(['en','ar'] as const)('uses the canonical composition and complete %s states',locale=>{
    state.locale=locale;
    const html=renderToStaticMarkup(<ReviewView caseId="synthetic-case"/>);
    expect(html).toContain(copy[locale].title);
    expect(html).toContain(copy[locale].reason);
    expect(html).toContain(copy[locale].empty);
    expect(html).toContain('bt-page-header');
    expect(html).not.toContain('<main');
  });
  it.each([0,1,1000,1000000])('shows the server total and bounded page for %i decisions',total=>{
    state.total=total;
    const html=renderToStaticMarkup(<ReviewView caseId="synthetic-case"/>);
    expect((html.match(/<li>/g)??[]).length).toBe(total?1:0);
    if(total) expect(html).toContain(total.toLocaleString('en'));
  });
  it('uses explicit Arabic digits for revision and server totals',()=>{
    state.locale='ar';state.total=1000;
    const html=renderToStaticMarkup(<ReviewView caseId="synthetic-case"/>);
    expect(html).toContain('١٬٠٠٠');
    expect(html).toContain(`${copy.ar.revision}: ١`);
  });
  it('removes the entire private form on a denied history read',()=>{
    state.historyError=new ApiError(403,'denied','synthetic-request');
    const html=renderToStaticMarkup(<ReviewView caseId="synthetic-case"/>);
    expect(html).toContain(copy.en.denied);
    expect(html).not.toContain('<textarea');
    expect(html).not.toContain('synthetic-case');
  });
  it('shows recovery when current data is uncertain even with an old answer',()=>{
    state.error=new ApiError(503,'unavailable','synthetic-request');
    const html=renderToStaticMarkup(<ReviewView caseId="synthetic-case"/>);
    expect(html).toContain(copy.en.retry);
    expect(html).not.toContain('<textarea');
  });
  it('shows unavailable without a session or case and keeps translation keys aligned',()=>{
    state.session=false;
    expect(renderToStaticMarkup(<ReviewView/>)).toContain(copy.en.unavailable);
    expect(Object.keys(copy.en).sort()).toEqual(Object.keys(copy.ar).sort());
  });
});
