import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { LocaleContext } from '@/shell/locale-context';
import type { ExternalOperation, ExternalState } from '@contracts/contracts-identity/external-sign-in';
import View from './view';
import fixtures from '../../../packages/contracts-identity/external-sign-in/fixtures.json';

describe('external account view', () => {
  for (const locale of ['en', 'ar'] as const) {
    it.each(['ready','pending','signed_in','linked','denied','stale','unavailable'] as ExternalState[])(`${locale} %s provides recovery`, state => {
      const operation = {...fixtures[0].operation, state} as ExternalOperation;
      const html = renderToStaticMarkup(createElement(LocaleContext.Provider, {value: locale},
        createElement(View, {accessPartition: 'private-current', operation, transport: async current => current})));
      expect(html).toContain('bt-page-header');
      expect(html).toContain('bt-state');
      expect(html).toContain(operation.operation_id);
      expect(html).toContain(`/account?lang=${locale}`);
      expect(html).not.toContain('<main');
      expect(html).not.toContain('undefined');
      if (state === 'pending') expect(html).toContain(locale === 'ar' ? 'التحقق من المرجع نفسه' : 'Check the same reference');
    });
    it(`${locale} defaults to honest unavailable`, () => {
      const html = renderToStaticMarkup(createElement(LocaleContext.Provider, {value: locale}, createElement(View, {accessPartition: 'visitor'})));
      expect(html).toContain(locale === 'ar' ? 'الدخول الخارجي غير متاح' : 'External sign-in unavailable');
    });
  }
});
