import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import fixture from '../../../../packages/contracts-orders/financial-reports/fixtures/current.v1.json';
import { dollars, validateReport } from '../../../../web/features/financial-reports/reads';
import { ReportContent } from '../../../../web/features/financial-reports/view';
import { copy } from '../../../../web/features/financial-reports/copy';
import type { Report, ReportRequest } from '../../../../packages/contracts-orders/financial-reports';

const request=fixture.request as ReportRequest;
const answer=fixture.success as Report;
vi.mock('../../../../web/features/identity/session',()=>({authenticatedRequest:vi.fn(),useSession:()=>null}));
describe('private receipts',()=>{
  it('validates the identical contract fixture and refuses mismatched scope or revision',()=>{
    expect(validateReport(answer,request)).toEqual(answer);
    expect(()=>validateReport(answer,{...request,operation_id:'other'})).toThrow();
    expect(()=>validateReport({...answer,revision:2},request)).toThrow();
    expect(()=>validateReport({...answer,state:'denied'},request)).toThrow();
    expect(()=>validateReport({...answer,trial_balance:{cash:0}},request)).toThrow();
  });
  it('rejects invalid money and missing or redirected receipts',()=>{
    for(const gross of [NaN,Infinity,0.5,Number.MAX_SAFE_INTEGER+1]){
      expect(()=>validateReport({...answer,totals:{...answer.totals!,gross}},request)).toThrow();
    }
    expect(()=>validateReport({...answer,items:[{...answer.items![0],watch_id:''}]},request)).toThrow();
    expect(()=>validateReport(answer,{...request,order_id:'other'})).toThrow();
  });
  it('prints complete equivalent English and Arabic commercial values',()=>{
    for(const locale of ['en','ar'] as const){
      const html=renderToStaticMarkup(<ReportContent answer={answer} locale={locale} onReceipt={()=>{}}/>);
      expect(html).toContain(copy[locale].simulated);
      expect(html).toContain(copy[locale].fee_collected);
      expect(html).toContain(dollars(500000,locale));
      expect(html).toContain('order-1');
      expect(html).not.toContain('<main');
    }
    expect(Object.keys(copy.en).sort()).toEqual(Object.keys(copy.ar).sort());
  });
  it('keeps exact integer cents at the safe boundary',()=>{
    expect(dollars(500000,'en')).toBe('$5,000.00');
    expect(dollars(1,'en')).toBe('$0.01');
    expect(dollars(Number.MAX_SAFE_INTEGER,'en')).toBe('$90,071,992,547,409.91');
    expect(dollars(-25000,'en')).toBe('−$250.00');
  });
  it('renders zero, one, large count and missing-data states honestly',()=>{
    const empty={...answer,items:[],total_count:0};
    expect(renderToStaticMarkup(<ReportContent answer={empty} locale="ar" onReceipt={()=>{}}/>)).toContain(copy.ar.empty);
    expect(renderToStaticMarkup(<ReportContent answer={{...answer,state:'pending',items:undefined,totals:undefined}} locale="en" onReceipt={()=>{}}/>)).toBe('');
    const long={...answer,items:[{...answer.items![0],order_id:'طلب طويل Latin ⌚ '.repeat(20)}],total_count:1000};
    expect(renderToStaticMarkup(<ReportContent answer={long} locale="ar" onReceipt={()=>{}}/>)).toContain('Latin ⌚');
  });
});

describe('private export lifetime',()=>{
  it('revokes a late export synchronously before the identity rerender',async()=>{
    const {ExportFence}=await import('../../../../web/features/financial-reports/export-fence');
    const events=new EventTarget(),fence=new ExportFence(events);
    const controller=fence.begin()!;
    expect(fence.accepts(controller)).toBe(true);
    events.dispatchEvent(new Event('bt:access-change'));
    expect(controller.signal.aborted).toBe(true);
    expect(fence.accepts(controller)).toBe(false);
    expect(fence.begin()).toBeNull();
    fence.dispose();
  });
  it('keeps the export alive through a locale-only change and retries after timeout',async()=>{
    const {ExportFence}=await import('../../../../web/features/financial-reports/export-fence');
    const events=new EventTarget(),fence=new ExportFence(events),controller=fence.begin()!;
    events.dispatchEvent(new Event('bt:locale-change'));
    expect(fence.accepts(controller)).toBe(true);
    fence.finish(controller);
    expect(fence.begin()).not.toBeNull();
    fence.dispose();
  });
  it('retains locale-independent read bindings for equivalent scope values',async()=>{
    const {readFileSync}=await import('node:fs');
    const source=readFileSync(new URL('../../../../web/features/financial-reports/view.tsx',import.meta.url),'utf8');
    expect(source).toContain('[scope.actor_id,scope.organization_id,scope.subject_id,scope.revision,page,size,order,view]');
    expect(source).not.toContain('[scope,page,size,order,view]');
    const {reportsRead}=await import('../../../../web/features/financial-reports/reads');
    expect(reportsRead('access',request).key).toEqual(reportsRead('access',{...request}).key);
  });
});

describe('current print authorization',()=>{
  it('checks the same reference and prints the fresh answer only',async()=>{
    const {ExportFence}=await import('../../../../web/features/financial-reports/export-fence');
    const {printCurrent}=await import('../../../../web/features/financial-reports/print-current');
    const fence=new ExportFence(new EventTarget()),print=vi.fn();
    const read=vi.fn(async()=>answer);
    expect(await printCurrent(fence,read,request,print)).toBe(true);
    expect(read).toHaveBeenCalledOnce();
    expect(print).toHaveBeenCalledWith(answer);
    fence.dispose();
  });
  it('blocks denied, uncertain, stale, failed and mismatched checks',async()=>{
    const {ExportFence}=await import('../../../../web/features/financial-reports/export-fence');
    const {printCurrent}=await import('../../../../web/features/financial-reports/print-current');
    const fence=new ExportFence(new EventTarget()),print=vi.fn();
    for(const state of ['denied','pending','stale','unavailable','drift'] as const){
      expect(await printCurrent(fence,async()=>({...answer,state,items:undefined,totals:undefined}),request,print)).toBe(false);
    }
    expect(await printCurrent(fence,async()=>{throw new Error('Timeout');},request,print)).toBe(false);
    expect(await printCurrent(fence,async()=>({...answer,operation_id:'other'}),request,print)).toBe(false);
    expect(print).not.toHaveBeenCalled();
    fence.dispose();
  });
  it('fences revocation while the check is in flight',async()=>{
    const {ExportFence}=await import('../../../../web/features/financial-reports/export-fence');
    const {printCurrent}=await import('../../../../web/features/financial-reports/print-current');
    const events=new EventTarget(),fence=new ExportFence(events),print=vi.fn();
    expect(await printCurrent(fence,async()=>{events.dispatchEvent(new Event('bt:access-change'));return answer;},request,print)).toBe(false);
    expect(print).not.toHaveBeenCalled();
    fence.dispose();
  });
});

describe('return visits',()=>{
  it('bounds retained identities without storing report answers',async()=>{
    const {ReportIdentities}=await import('../../../../web/features/financial-reports/reads');
    const identities=new ReportIdentities(new EventTarget());
    identities.retain('access',request);
    for(let page=2;page<=1001;page++) identities.retain('access',{...request,page,operation_id:`page-${page}`});
    const revisited={...request,operation_id:'after-eviction'};
    expect(identities.retain('access',revisited)).toBe(revisited);
    identities.dispose();
  });
  it('reuses the held answer and reference while checking the current read again',async()=>{
    const {createReadScope}=await import('../../../../web/lib/page-speed/scope');
    const {optionsFor}=await import('../../../../web/lib/page-speed/definition');
    const {ReportIdentities,reportsRead}=await import('../../../../web/features/financial-reports/reads');
    const events=new EventTarget(),identities=new ReportIdentities(events);
    const retainedReportRequest=(_scope:unknown,fingerprint:string,draft:ReportRequest)=>identities.retain(fingerprint,draft);
    const scope=createReadScope('member:access');
    identities.retain('access',request);
    const first=optionsFor(scope,reportsRead('access',request));
    scope.client.setQueryData(first.queryKey,answer);
    const returning=retainedReportRequest(scope,'access',{...request,operation_id:'new-mount'});
    expect(returning).toEqual(request);
    const next=optionsFor(scope,reportsRead('access',returning));
    expect(scope.client.getQueryData(next.queryKey)).toEqual(answer);
    expect(next.staleTime).toBe(0);
    const {authenticatedRequest}=await import('../../../../web/features/identity/session');
    vi.mocked(authenticatedRequest).mockResolvedValueOnce(answer);
    await scope.client.fetchQuery(next);
    expect(authenticatedRequest).toHaveBeenCalled();
    for(const change of [{page:2},{expected_revision:2},{subject_id:'other'},{organization_id:'other'}]){
      const draft={...request,...change,operation_id:'new-binding'};
      expect(retainedReportRequest(scope,'access',draft)).toBe(draft);
    }
    const other={...request,operation_id:'other-access'};
    expect(retainedReportRequest(scope,'other',other)).toBe(other);
    events.dispatchEvent(new Event('bt:access-change'));
    scope.clear();
    expect(retainedReportRequest(scope,'access',other)).toBe(other);
    expect(scope.client.getQueryData(next.queryKey)).toBeUndefined();
    identities.dispose();
  });
});
