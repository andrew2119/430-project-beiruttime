import { createElement, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { copy } from './copy';
const current = vi.hoisted(() => ({ state: 'restoring', locale: 'en' as 'en' | 'ar' }));
vi.mock('@/features/identity/session', () => ({
  useSession: () => null, useSessionState: () => current.state,
  refreshSession: vi.fn(), authenticatedRequest: vi.fn(),
}));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => current.locale }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock('@/shell/page-header', () => ({
  PageLayout: ({children}: {children: ReactNode}) => createElement('section', null, children),
  PageHeader: () => null,
}));
vi.mock('@beirut-time/ui', () => ({
  State: ({body, children, kind}: {body: string; children?: ReactNode; kind: string}) => createElement('div', {'data-state': kind}, body, children),
  Button: ({children, onClick}: {children: ReactNode; onClick: () => void}) => createElement('button', {onClick}, children),
  ButtonLink: ({children, href}: {children: ReactNode; href: string}) => createElement('a', {href}, children),
}));
import LifecyclePage from './view';

describe.each(['en', 'ar'] as const)('session recovery in %s', locale => {
  it.each(['restoring', 'unavailable', 'signed-out'])('renders actionable %s state', state => {
    current.locale = locale;
    current.state = state;
    const html = renderToStaticMarkup(createElement(LifecyclePage));
    const t = copy[locale];
    expect(html).not.toContain('<form');
    if (state === 'restoring') {
      expect(html).toContain('data-state="loading"');
      expect(html).toContain(t.sessionLoading);
      expect(html).not.toContain(t.signInAction);
    } else if (state === 'unavailable') {
      expect(html).toContain(t.sessionUnavailable);
      expect(html).toContain(`<button>${t.sessionRetry}</button>`);
      expect(html).not.toContain('href=');
    } else {
      expect(html).toContain(t.signIn);
      expect(html).toContain(`href="/${locale}/account"`);
      expect(html).toContain(t.signInAction);
    }
  });
});
