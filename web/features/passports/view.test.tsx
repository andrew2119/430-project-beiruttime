import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { LocaleContext } from '@/shell/locale-context';
import { PassportView } from './view';
import type { PassportState } from '../../../packages/contracts-trust/passports/v1';
import en from './en.json';
import ar from './ar.json';

const render = (locale:'en'|'ar',answer:PassportState) => renderToStaticMarkup(<LocaleContext.Provider value={locale}><PassportView answer={answer} retry={()=>{}}/></LocaleContext.Provider>);
describe('passport bilingual recovery', () => {
  it.each(['empty','denied','pending','unavailable','invalid'] as const)('retains %s and the exact action reference through locale changes', state => {
    const answer = {state,operation_id:'00000000-0000-0000-0000-000000000001'};
    for (const locale of ['en','ar'] as const) {
      const html = render(locale,answer);
      expect(html).toContain(answer.operation_id);
      expect(html).toContain((locale === 'ar' ? ar : en)[state]);
      expect(html).toContain('type="button"');
      expect(html).not.toContain('<main');
    }
    expect(answer.state).toBe(state);
  });
  it('uses the same complete dictionary and reserves a first answer', () => {
    expect(Object.keys(ar).sort()).toEqual(Object.keys(en).sort());
    expect(render('ar',{state:'loading'})).toContain('aria-busy="true"');
  });
  it('renders only the historical public allowlist in either language', () => {
    const answer:PassportState = {state:'verified',document:{key_id:'key',signature:'signature',summary:{schema_version:'passports.summary.v1',passport_id:'passport',issuer_id:'issuer',inspected_at:'2026-11-17T12:00:00Z',issued_at:'2026-11-17T12:00:00Z',scope:'independent_private_sale_inspection',watch_reference:'safe-reference',inspected_revision:1,claim:'historical_inspection_summary_only'}}};
    for (const locale of ['en','ar'] as const) {
      const html = render(locale,answer);
      expect(html).toContain('safe-reference');
      expect(html).toContain((locale === 'ar' ? ar : en).historical);
      expect(html).not.toContain('signature');
    }
  });
});
