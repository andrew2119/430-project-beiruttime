import { beforeEach, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { Session } from '@contracts/contracts-identity/accounts';
import en from './en.json';
import type { HeldSampleTab } from './sample-accounts';

// The account page in a sample tab: the shell's Sign in link and every page's sign-in prompt
// lead here, so a signed-out sample tab must show its own status, never a password box.
const owner = vi.hoisted(() => ({ session: null as Session | null, held: null as HeldSampleTab | null }));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => 'en' }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock('next/link', () => ({ default: 'a' }));
vi.mock('./session', () => ({
  useSession: () => owner.session, useSessionState: () => owner.session ? 'authenticated' : 'signed-out',
  accountApi: '/api/web/v1/identity/v1/accounts', beginSession: vi.fn(), authenticatedRequest: vi.fn(),
  refreshSession: vi.fn(), signOut: vi.fn(), safeReturnPath: (value: string) => value,
  signInHref: () => '/en/account', enterSampleSession: vi.fn(), openSessionSlot: vi.fn(),
}));
vi.mock('./sample-accounts', async original => ({
  ...await original<typeof import('./sample-accounts')>(), useHeldSampleTab: () => owner.held,
}));
import AccountView from './account-view';

const staff: Session = { access_token: 'memory-only', token_type: 'Bearer', expires_in: 300, account: { id: 'staff', email: 'staff.demo@example.test', display_name: 'Staff' }, principal: { actor: { subject_id: 'staff', session_id: 'lineage', organization_id: null }, roles: ['buyer'], permissions: [], organizations: [], organization_grants: [] }, access_fingerprint: 'one-way-scope' };
const passwordBox = /<input[^>]*type="password"/;
beforeEach(() => { owner.session = null; owner.held = null; });

it.each(['signin', 'register', 'recovery', 'reset'] as const)('shows a signed-out sample tab its own status on the %s page, with no password box or form', mode => {
  owner.held = { set: 'demo', role: 'staff', key: null };
  const html = renderToStaticMarkup(createElement(AccountView, { initialMode: mode }));
  expect(html).toContain('data-sample-signed-out="staff"');
  expect(html).toContain('data-sample-set="demo"');
  expect(html).toContain('<bdi>staff.demo@example.test</bdi>');
  expect(html).toContain(en.sampleSignedOut);
  expect(html).toContain(`>${en.sample_staff}</h2>`);
  expect(html).not.toMatch(passwordBox);
  expect(html).not.toContain('<form');
  expect(html).not.toContain('role="alert"');
});

it('shows a signed-out Operator tab its plain status with no address, password box or form', () => {
  owner.held = { set: 'click-test', role: 'operator', key: null };
  const html = renderToStaticMarkup(createElement(AccountView, { initialMode: 'signin' }));
  expect(html).toContain('data-sample-signed-out="operator"');
  expect(html).toContain(en.sampleOperatorAccount);
  expect(html).toContain(en.sampleSignedOut);
  expect(html).toContain(`>${en.sample_operator}</h2>`);
  expect(html).not.toContain('<bdi>');
  expect(html).not.toContain(en.sample_account_unavailable);
  expect(html).not.toMatch(passwordBox);
  expect(html).not.toContain('<form');
  expect(html).not.toContain('role="alert"');
});

it('shows a signed-in sample tab its account with no password change', () => {
  owner.held = { set: 'demo', role: 'staff', key: null };
  owner.session = staff;
  const html = renderToStaticMarkup(createElement(AccountView));
  expect(html).toContain('<bdi>staff.demo@example.test</bdi>');
  expect(html).not.toMatch(passwordBox);
  expect(html).not.toContain('data-sample-signed-out');
});

it('leaves an ordinary tab its sign-in form and password change', () => {
  expect(renderToStaticMarkup(createElement(AccountView))).toMatch(passwordBox);
  owner.session = staff;
  expect(renderToStaticMarkup(createElement(AccountView))).toMatch(passwordBox);
});
