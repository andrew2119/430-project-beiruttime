import { beforeEach, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import en from './en.json';
import ar from './ar.json';
import movementEn from '../movement-option/en.json';
import requestEn from '../request-drafts/en.json';
import requestAr from '../request-drafts/ar.json';
const state = vi.hoisted(() => ({ locale: 'en' as 'en' | 'ar', pending: false, error: false }));
const brand = '00000000-0011-4000-8000-000000000001';
vi.mock('next/link', () => ({ default: 'a' }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }), useSearchParams: () => new URLSearchParams('business='+brand) }));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => state.locale }));
vi.mock('@/shell/access-context', () => ({ useAccessContext: () => ({ fingerprint: 'synthetic', roles: ['buyer'] }) }));
vi.mock('@/features/identity/session', () => ({ useSession: () => ({ access_fingerprint: 'synthetic', principal: { roles: ['buyer'] } }), signInHref: () => '/en/account', authenticatedRequest: vi.fn(), refreshSession: vi.fn() }));
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ setQueryData: vi.fn(), invalidateQueries: vi.fn() }),
  useMutation: () => ({ mutate: vi.fn(), reset: vi.fn(), isPending: false, isError: false }),
  useQuery: ({ queryKey }: { queryKey: string[] }) => ({ data: queryKey[0] === 'l08-drafts' ? { items: [] } : queryKey[0].startsWith('l08-') || queryKey[0] === 'movement-option' || queryKey[0] === 'official-business' ? undefined : { choice: null, selection: null }, isPending: false, isError: false }),
  useInfiniteQuery: ({ queryKey }: { queryKey: string[] }) => ({
    isPending: state.pending, isError: state.error, error: state.error ? new Error('synthetic') : null,
    isSuccess: !state.pending && !state.error, refetch: vi.fn(), hasNextPage: false,
    data: { pages: [{ status: 'available', data: { items: [], next_after: null }, items: queryKey[0] === 'official-directory' ? [{ organization_id: brand, revision: 1, display_name: 'Sample official brand', kind: 'brand', sample: true, capabilities: ['maintenance', 'customization'], contact: 'sample@example.invalid', visit_en: 'By arrangement', visit_ar: 'بموعد مسبق', scope_en: 'Indicative scope', scope_ar: 'نطاق إرشادي' }] : [{ id: 'movement', brand_id: brand, revision: 1, label_en: 'Sample movement', label_ar: 'حركة نموذجية', caliber: 'manual-01', cases: ['case'], dials: ['dial'], hands: ['hands'], functions: [], quote_minor: 15000, currency: 'USD' }] }] },
  }),
}));
import Directory from './view';
import RequestDrafts from '../request-drafts/request-drafts';
beforeEach(() => { state.locale = 'en'; state.pending = false; state.error = false; });
it.each(['en', 'ar'] as const)('composes the directory and movement form inside one shared header in %s', locale => {
  state.locale = locale;
  const html = renderToStaticMarkup(createElement(Directory));
  expect(html.match(/<h1\b/g)).toHaveLength(1);
  expect(html).toContain('hx-title');
  expect(html).toContain(locale === 'en' ? en.title : ar.title);
  expect(html).toContain(`/${locale}/services?purpose=customization`);
  expect(html).toContain('pg-seg-item-active');
  expect(html).toContain('ui-card');
  expect(html).toContain('Sample official brand');
  expect(html).toContain('manual-01');
  expect(html).toContain('pg-chonk-primary');
  if (locale === 'en') expect(html).toContain(movementEn.save);
});
it.each(['pending', 'error'] as const)('uses the shared directory %s face', phase => {
  state.pending = phase === 'pending'; state.error = phase === 'error';
  const html = renderToStaticMarkup(createElement(Directory));
  expect(html).toContain('pg-face-card');
  expect(html).toContain(`data-kind="${phase === 'pending' ? 'loading' : 'error'}"`);
});
it.each(['en', 'ar'] as const)('keeps request draft controls, native POST and translated header in %s', locale => {
  state.locale = locale;
  const html = renderToStaticMarkup(createElement(RequestDrafts));
  expect(html.match(/<h1\b/g)).toHaveLength(1);
  expect(html).toContain(locale === 'en' ? requestEn.title : requestAr.title);
  expect(html).toContain('method="post"');
  for (const name of ['kind', 'brand_id', 'watch_context', 'watch_reference', 'scope_intent', 'notes']) expect(html).toContain(`name="${name}"`);
  expect(html).toContain('ui-textarea');
});
