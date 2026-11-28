import { describe, expect, it } from 'vitest';
import { readPassport, type PublicRequest } from './read';
import fixture from '../../../packages/contracts-trust/passports/fixtures.json';
import { renderToStaticMarkup } from 'react-dom/server';
import { PageReadProvider } from '@/lib/page-speed/provider';
import { shellForPath } from '@/shell/foundation/path';
import { LocaleContext } from '@/shell/locale-context';
import Page from '../../app/(passports)/passports/[passport_id]/page';

const id = fixture.signed.summary.passport_id;
describe('public passport read', () => {
  it('requires an actual verification response and retries the identical reference', async () => {
    const calls:string[] = [];
    const request:PublicRequest = async (method,path,document) => {
      calls.push(`${method} ${path}`);
      if (method === 'POST') expect(document).toEqual(fixture.signed);
      return Response.json(fixture.signed);
    };
    const first = await readPassport(id,request);
    expect(first).toEqual({state:'verified',document:fixture.signed});
    expect(await readPassport(id,request)).toEqual(first);
    expect(calls.slice(0,2)).toEqual([`GET /public/v1/passports/${id}`,'POST /public/v1/passports/verify']);
    expect(calls.slice(2)).toEqual(calls.slice(0,2));
  });
  it.each([[404,'empty'],[403,'denied'],[202,'pending'],[503,'unavailable'],[422,'invalid']] as const)('maps %s honestly',async (status,state) => {
    expect(await readPassport(id,async ()=>new Response(null,{status}))).toEqual({state});
  });
  it('rejects tampering, wrong issuer, private fields, malformed data and wrong references', async () => {
    for (const field of ['issuer_id','watch_reference','inspected_revision']) {
      const changed = structuredClone(fixture.signed);
      Object.assign(changed.summary,{[field]:field === 'inspected_revision' ? 2 : '00000000-0000-0000-0000-000000000099'});
      expect(await readPassport(id,async method=> method === 'GET' ? Response.json(changed) : new Response(null,{status:422}))).toEqual({state:'invalid'});
    }
    for (const document of [{...fixture.signed,private_owner:'restricted'}, {...fixture.signed,summary:{...fixture.signed.summary,evidence_refs:['restricted']}}, {...fixture.signed,summary:{...fixture.signed.summary,passport_id:'wrong'}}, {}]) {
      let calls = 0;
      expect(await readPassport(id,async ()=>{calls++;return Response.json(document);})).toEqual({state:'invalid'});
      expect(calls).toBe(1);
    }
  });
  it('fails closed after a read when verification times out or returns a different summary',async () => {
    expect(await readPassport(id,async method=>method === 'GET' ? Response.json(fixture.signed) : {kind:'unavailable'})).toEqual({state:'unavailable'});
    expect(await readPassport(id,async ()=>{throw new Error('timeout');})).toEqual({state:'unavailable'});
    let calls = 0;
    expect(await readPassport('invalid',async ()=>{calls++;return Response.json(fixture.signed);})).toEqual({state:'empty'});
    expect(calls).toBe(0);
    expect(await readPassport(id,async method=>Response.json(method === 'GET' ? fixture.signed : {...fixture.signed,signature:'a'.repeat(86)}))).toEqual({state:'invalid'});
  });
  it.each(['', '/en', '/ar'])('selects the shared shell for direct and committed %s destinations', prefix => {
    const path = `${prefix}/passports/${id}`;
    expect(shellForPath(path,null)).toBe('foundation');
    expect(shellForPath('/internal/page',path)).toBe('foundation');
  });
  it('mounts the public destination in both languages through the selected shared scope',async () => {
    const page = await Page({params:Promise.resolve({passport_id:id})});
    for (const locale of ['en','ar'] as const) {
      const path = `/passports/${id}`;
      const shell = shellForPath(path,null);
      expect(shell).toBe('foundation');
      const content = shell === 'foundation' ? <PageReadProvider>{page}</PageReadProvider> : page;
      const html = renderToStaticMarkup(<LocaleContext.Provider value={locale}>{content}</LocaleContext.Provider>);
      expect(html).toContain('aria-busy="true"');
      expect(html).toContain(locale === 'ar' ? 'التحقق من ملخص الفحص' : 'Verify inspection summary');
      expect(html).not.toContain('<main');
    }
  });
});
