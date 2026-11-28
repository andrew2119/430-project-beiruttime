import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { emptyFilters, queryFrom } from '../../../../web/features/audit-references/filters';
import { copy } from '../../../../web/features/audit-references/copy';
const current=vi.hoisted(()=>({locale:'en' as 'en'|'ar',session:null as unknown,state:'signed-out',result:{} as unknown}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>current.locale}));
vi.mock('@/features/identity/session',()=>({useSession:()=>current.session,useSessionState:()=>current.state,refreshSession:vi.fn(),authenticatedRequest:vi.fn()}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>current.result}));
vi.mock('@/lib/page-speed/arrival',()=>({AnswerArrival:({children}:{children:React.ReactNode})=>children}));
import { ApiError } from '../../../../web/lib/api/client';
import AuditScreen, { AuditReadBoundary, SourcePanel } from '../../../../web/features/audit-references/screen';
const fixture=JSON.parse(readFileSync(new URL('../../../../packages/contracts-comms/audit-references/fixtures.json',import.meta.url),'utf8'));
const draft={...emptyFilters,organization:fixture.query.organization_id,operation:fixture.query.operation_id,after:fixture.query.after,before:fixture.query.before};

describe('private audit filters and bilingual states',()=>{
  it('declares the private feature page with the exact page-table fields',()=>{
    const declaration=JSON.parse(readFileSync(new URL('../../../../web/features/audit-references/delivery-contract.json',import.meta.url),'utf8'));
    expect(Object.keys(declaration).sort()).toEqual(['route','file','view','kind','reason','content','read','proof'].sort());
    expect(declaration).toMatchObject({route:'/operations/audit',file:'web/app/(audit-references)/operations/audit/page.tsx',view:'web/features/audit-references/screen.tsx',kind:'reads',content:'[data-page-answer]',read:'audit-references.v1',proof:'owed'});
    expect(declaration.reason.length).toBeGreaterThan(0);
  });
  it('keeps exact references and filters across language reads',()=>{
    const value={...draft,actor:fixture.success.items[0].actor_id,outcome:'accepted'};
    const english=queryFrom(value);current.locale='ar';const arabic=queryFrom(value);
    expect(arabic).toEqual(english);expect(value.actor).toBe(fixture.success.items[0].actor_id);
    expect(Object.keys(copy.en).sort()).toEqual(Object.keys(copy.ar).sort());
  });
  it.each([
    {before:draft.after},{before:'2026-12-03T00:00:00Z'},{after:'2026-11-01T01:00:00+01:00'},
    {actor:'private text'},{operation:''},{outcome:'approved'},
  ])('rejects invalid or unbounded filters %j',change=>{expect(queryFrom({...draft,...change})).toBeNull();});
  for(const locale of ['en','ar'] as const){
    it(`${locale}: denies ordinary users without private rows`,()=>{
      current.locale=locale;current.session={access_fingerprint:'current',principal:{roles:['buyer'],actor:{organization_id:draft.organization},organization_grants:[]}};
      const html=renderToStaticMarkup(<AuditScreen/>);
      expect(html).toContain(copy[locale].denied);expect(html).not.toContain(fixture.success.items[0].operation_id);
    });
    it(`${locale}: renders the same labeled filter identity`,()=>{
      current.locale=locale;current.session={access_fingerprint:'current',principal:{roles:['operator'],actor:{organization_id:draft.organization},organization_grants:[{organization_id:draft.organization,permissions:['audit.references.read']}]}};
      const html=renderToStaticMarkup(<AuditScreen/>);
      expect(html).toContain(copy[locale].after);expect(html).toContain(copy[locale].operation);expect(html.match(/<input/g)).toHaveLength(6);
      expect(html).not.toContain('<main');
    });
    it(`${locale}: shows owner totals and revision links without evidence`,()=>{
      current.locale=locale;current.result={isPending:false,isError:false,isFetching:false,data:{results:[{source:'trust',state:'ready',page:fixture.success}]},refetch:vi.fn()};
      const html=renderToStaticMarkup(<SourcePanel source="trust" initial={fixture.query} scope="current"/>);
      expect(html).toContain(copy[locale].inspect);expect(html).toContain(fixture.success.items[0].reason_reference);expect(html).not.toContain('evidence');
    });
    it.each(['denied','stale','pending','unavailable','empty'] as const)(`${locale}: honest %s recovery`,state=>{
      current.locale=locale;current.result={isPending:false,isError:false,isFetching:false,data:{results:[{source:'trust',state,page:null}]},refetch:vi.fn()};
      const html=renderToStaticMarkup(<SourcePanel source="trust" initial={fixture.query} scope="current"/>);
      expect(html).toContain(copy[locale][state]);expect(html).not.toContain(fixture.success.items[0].operation_id);
    });
  }
  it.each(['en','ar'] as const)('%s: composition failure has no ineffective retry',locale=>{
    const boundary=new AuditReadBoundary({t:copy[locale],children:null});
    boundary.state={unavailable:true};
    const html=renderToStaticMarkup(boundary.render());
    expect(html).toContain(copy[locale].readUnavailable);
    expect(html).not.toContain('<button');
  });
  it.each([401,403])('maps current access failure %s without held rows',status=>{
    current.locale='en';current.result={isPending:false,isError:true,error:new ApiError(status,'denied',''),data:{results:[{source:'trust',state:'ready',page:fixture.success}]},refetch:vi.fn()};
    const html=renderToStaticMarkup(<SourcePanel source="trust" initial={fixture.query} scope="current"/>);
    expect(html).toContain(status===401?copy.en.signIn:copy.en.denied);expect(html).not.toContain(fixture.success.items[0].operation_id);
  });
  it('drops retained private rows on failure',()=>{
    current.result={isPending:false,isError:true,isFetching:false,data:{results:[{source:'trust',state:'ready',page:fixture.success}]},refetch:vi.fn()};
    expect(renderToStaticMarkup(<SourcePanel source="trust" initial={fixture.query} scope="current"/>)).not.toContain(fixture.success.items[0].operation_id);
  });
});
