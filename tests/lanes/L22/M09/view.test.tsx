import React from 'react';
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { RecordCard } from '../../../../web/features/transaction-email/record';
import { copy } from '../../../../web/features/transaction-email/copy';
import type { EmailRecord } from '../../../../packages/contracts-comms/transaction-email';

const record:EmailRecord = {
  schema_version:'transaction-email.v1',operation_id:'00000000-0000-4000-8000-000000000001',
  subject_id:'00000000-0000-4000-8000-000000000004',watch_id:'00000000-0000-4000-8000-000000000005',
  actor_id:'00000000-0000-4000-8000-000000000003',organization_id:null,expected_revision:4,revision:2,
  state:'possibly_sent',attempt_id:'00000000-0000-4000-8000-000000000006',locale:'en',kind:'confirmation',synthetic:true,
  pending_reason:'delivery_unknown',next_actor:'00000000-0000-4000-8000-000000000007',next_review_at:'2026-11-18T10:01:00Z',available_at:'2026-11-17T10:01:00Z',
  authenticated_link:'/en/notification-email?operation_id=00000000-0000-4000-8000-000000000001',
};
describe('private delivery presentation',()=>{
  for (const locale of ['en','ar'] as const) for (const state of ['captured','recorded','failed','possibly_sent'] as const) {
    it(`${locale} ${state} retains the exact operation and times`,()=>{
      const before = JSON.stringify(record);
      const html = renderToStaticMarkup(<RecordCard record={{...record,state}} locale={locale} opening={false} open={()=>{}}/>);
      expect(html).toContain(copy[locale][state]);
      expect(html).toContain(record.operation_id);
      expect(html).toContain('dir="ltr"');
      expect(html).toContain(record.available_at);
      expect(html).toContain(record.next_review_at);
      expect(html).not.toContain(record.watch_id);
      expect(html).not.toContain(record.actor_id);
      expect(JSON.stringify(record)).toBe(before);
    });
  }
  it('has complete matching recovery and category dictionaries',()=>{
    expect(Object.keys(copy.en)).toEqual(Object.keys(copy.ar));
    for (const text of Object.values(copy.ar)) expect(text).toMatch(/[\u0600-\u06ff]/);
  });
  it('disables concurrent destination requests in the control',()=>{
    const html = renderToStaticMarkup(<RecordCard record={record} locale="ar" opening open={()=>{}}/>);
    expect(html).toContain('disabled');
    expect(html).toContain('aria-busy="true"');
  });
});

import TransactionEmailPage from '../../../../web/features/transaction-email/page';
import { LocaleContext } from '../../../../web/shell/locale-context';
for (const locale of ['en','ar'] as const) {
  it(`${locale} fails closed while shared composition is unavailable`,()=>{
    const html = renderToStaticMarkup(<LocaleContext value={locale}><TransactionEmailPage/></LocaleContext>);
    expect(html).toContain(copy[locale].error);
    expect(html).toContain(copy[locale].retry);
    expect(html).not.toContain(record.operation_id);
    expect(html).not.toContain('<main');
  });
}
