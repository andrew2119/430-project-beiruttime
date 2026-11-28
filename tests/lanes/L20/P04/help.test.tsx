import { describe, expect, it } from '../../../../web/node_modules/vitest/dist/index.js';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import HelpPolicies from '../../../../web/features/help-policies/view';
import { helpMatches, policyGuidance } from '../../../../web/features/help-policies/model';
import { LocaleContext } from '../../../../web/shell/locale-context';
import fixtures from '../../../../packages/contracts-comms/help-policies/fixtures.v1.json';
import schema from '../../../../packages/contracts-comms/help-policies/accepted-terms.v1.schema.json';

const require = createRequire(fileURLToPath(new URL('../../../../web/node_modules/eslint/package.json',import.meta.url)));
const SchemaValidator = require('ajv');

describe('versioned help',()=>{
  it('validates deterministic responses and rejects private data in denied states',()=>{
    const validator = new SchemaValidator({allErrors:true});
    const validate = validator.compile({...schema,$schema:'http://json-schema.org/draft-07/schema#'});
    for (const fixture of Object.values(fixtures)) expect(validate(fixture),JSON.stringify(validate.errors)).toBe(true);
    expect(validate({...fixtures.denied,artifact:fixtures.ready.artifact})).toBe(false);
    expect(validate({...fixtures.ready,artifact:{...fixtures.ready.artifact,accepted_at:'2026-11-16T10:00:00+00:00'}})).toBe(true);
  });
  it('keeps the same query and results across reading languages',()=>{
    const query = 'رسوم';
    const matches = helpMatches(query);
    expect(matches.length).toBeGreaterThan(0);
    expect(helpMatches(query).map(item=>item.id)).toEqual(matches.map(item=>item.id));
    expect(helpMatches('Whish Money').map(item=>item.id)).toContain('payments');
  });
  it('handles empty, one, long mixed text, emoji and a thousand finite records',()=>{
    expect(helpMatches('missing-🙂')).toEqual([]);
    expect(helpMatches('anything',[])).toEqual([]);
    const article = {id:'sample',en:{title:'ساعة Watch 🙂',body:'x'.repeat(1000)},ar:{title:'ساعة Watch 🙂',body:'نص'}};
    expect(helpMatches('🙂',[article])).toHaveLength(1);
    expect(helpMatches('🙂',Array.from({length:1000},(_,index)=>({...article,id:String(index)})))).toHaveLength(1000);
    expect(helpMatches('x'.repeat(1000),[article])).toHaveLength(1);
  });
  for (const locale of ['en','ar'] as const) it(`renders every section and public unavailable recovery in ${locale}`,()=>{
    const html=renderToStaticMarkup(createElement(LocaleContext.Provider,{value:locale},createElement(HelpPolicies)));
    expect(html).not.toContain('<main');
    expect(html).toContain('help-search');
    for (const article of policyGuidance.articles) expect(html).toContain(article[locale].title);
    expect(html).toContain(locale==='ar'?'تفاصيل الاتصال غير متاحة':'Contact details unavailable');
    expect(html).toContain('E03');
    expect(html).not.toContain('sample-person');
  });
});
