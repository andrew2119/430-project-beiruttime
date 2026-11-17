import { PageReadProvider } from '@/lib/page-speed/provider';
import type { ComponentProps } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, expect, it, vi } from 'vitest';
import type { CommandForm } from './command-form';
const state = vi.hoisted(() => ({
  locale: 'en',
  submit: null as ComponentProps<typeof CommandForm>['submit'] | null,
  request: vi.fn(),
}));
vi.mock('./command-form', async original => ({ ...await original<typeof import('./command-form')>(), CommandForm: (props: ComponentProps<typeof CommandForm>) => {
  state.submit = props.submit;
  return <form>{props.children}</form>;
} }));
vi.mock('./transport', () => ({ businessRequest: state.request }));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => state.locale }));
vi.mock('@/shell/access-context', () => ({ useAccessContext: () => ({ fingerprint: 'test-access' }) }));
vi.mock('@/features/identity/session', () => ({ useSession: () => ({
  principal: { permissions: ['identity.businesses.manage'], roles: ['operator'] },
}) }));
vi.mock('next/navigation', () => ({ usePathname: () => '/business' }));
import BusinessDirectory from './directory';
import { BusinessOperation } from './operation-v2';
import en from './en.json';
import ar from './ar.json';

beforeEach(() => { state.request.mockReset(); });

it.each(['en', 'ar'])('submits exact real-business confirmation in %s and recovers unchanged after a language switch', async locale => {
  state.locale = locale;
  const copy = locale === 'ar' ? ar : en;
  const html = renderToStaticMarkup(<PageReadProvider><BusinessDirectory /></PageReadProvider>);
  expect(html).toContain(copy.confirmationReference);
  expect(html).toContain(copy.confirmedScope);
  expect(html).toContain('name="confirmation_ref"');
  expect(html.match(/name="confirmed_scope"/g)).toHaveLength(3);
  const form = new FormData();
  Object.entries({
    legal_name: 'Synthetic test business', public_name: 'Synthetic test business',
    kind: 'brand', assurance: 'test-assurance', reason: 'Recorded business confirmation',
    confirmation_ref: '00000000-0000-0000-0000-000000000022',
  }).forEach(([key, value]) => form.set(key, value));
  for (const capability of ['sales', 'servicing']) {
    form.append('capabilities', capability);
    form.append('confirmed_scope', capability);
  }
  const operation = new BusinessOperation();
  state.request.mockRejectedValueOnce(new TypeError('Response unavailable'))
    .mockResolvedValue({ revision: 1, state: 'active' });
  await expect(state.submit!(form, operation)).rejects.toThrow();
  const original = state.request.mock.calls[0];
  expect(JSON.parse(original[1].body)).toMatchObject({
    sample: false, confirmation_ref: form.get('confirmation_ref'),
    confirmed_scope: ['sales', 'servicing'], capabilities: ['sales', 'servicing'],
  });
  state.locale = locale === 'en' ? 'ar' : 'en';
  renderToStaticMarkup(<PageReadProvider><BusinessDirectory /></PageReadProvider>);
  await expect(operation.recover()).resolves.toMatchObject({ operation_state: 'committed' });
  expect(state.request.mock.calls[1]).toEqual(original);
});
