import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';
import type { FormDraft } from './model';
import { formReducer } from './model';
import { copy } from './copy';
import MinimumOffers, { type ScreenProps } from './view';

const mounted = vi.hoisted(() => ({
  draft: { amount: null, operation: null } as FormDraft,
  locale: 'en' as 'en' | 'ar',
  buttons: new Map<string, () => void>(),
}));
vi.mock('react', async () => ({
  ...await vi.importActual('react'),
  useReducer: () => [mounted.draft, (action: Parameters<typeof formReducer>[1]) => {
    mounted.draft = formReducer(mounted.draft, action);
  }],
}));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => mounted.locale }));
vi.mock('@/shell/foundation/page', () => ({
  PageFrame: ({ children }: { children: React.ReactNode }) => children,
  PageBody: ({ children }: { children: React.ReactNode }) => children,
  PageHeader: () => null,
}));
vi.mock('@beirut-time/ui/foundation', () => ({
  Card: ({ children }: { children: React.ReactNode }) => children,
  State: ({ title }: { title: string }) => <p>{title}</p>,
  Input: () => null,
  Button: ({ children, onClick }: { children: string; onClick?: () => void }) => {
    if (onClick) mounted.buttons.set(children, onClick);
    return <button>{children}</button>;
  },
}));

it('reloads unavailable access without replacing a pending command, then retries it in either language', async () => {
  const command = {
    schema_version: 1 as const, operation_id: 'original', actor_id: 'seller', organization_id: 'business',
    subject_id: 'listing', watch_id: 'watch', expected_revision: 0, source_revision: 2,
    policy_revision: 3, quote_id: 'quote', quote_revision: 4, minimum_minor: 10000,
  };
  for (const locale of ['en', 'ar'] as const) {
    mounted.locale = locale;
    mounted.draft = { amount: null, operation: null };
    const gateway = { reload: vi.fn(), save: vi.fn().mockRejectedValue(new Error('unavailable')) };
    const props: ScreenProps = { scopeKey: 'same-scope', gateway, state: 'ready', current: {
      revision: 0, minimum_minor: null, binding: command,
    } };
    let mountedKey: string | null | undefined;
    const render = (next: ScreenProps) => {
      const form = MinimumOffers(next);
      if (mountedKey !== form.key) {
        mounted.draft = { amount: null, operation: null };
        mountedKey = form.key;
      }
      mounted.buttons.clear();
      return renderToStaticMarkup(form);
    };
    render(props);
    mounted.draft = { amount: '١٠٠', operation: { phase: 'pending', command } };
    const draft = mounted.draft;
    expect(render(props)).toContain(copy[locale].retry);
    expect(render({ ...props, state: 'unavailable', current: undefined })).toContain(copy[locale].reload);
    mounted.buttons.get(copy[locale].reload)!();
    expect(gateway.reload).toHaveBeenCalledOnce();
    expect(mounted.draft).toBe(draft);
    expect(mounted.draft.operation?.command).toBe(command);
    render({ ...props, state: 'loading', current: undefined });
    render({ ...props, current: { ...props.current!, revision: 1, minimum_minor: 10000 } });
    expect(mounted.draft).toBe(draft);
    mounted.buttons.get(copy[locale].retry)!();
    await Promise.resolve();
    await Promise.resolve();
    expect(gateway.save).toHaveBeenCalledOnce();
    expect(gateway.save.mock.calls[0][0]).toBe(command);
    expect(mounted.draft.operation?.command).toBe(command);
    expect(mounted.draft.operation?.phase).toBe('pending');
    mounted.draft = { amount: '100', operation: { phase: 'stale', command } };
    render(props);
    mounted.buttons.get(copy[locale].reload)!();
    expect(mounted.draft).toEqual({ amount: null, operation: null });
    for (const scopeKey of ['new-actor', 'new-business', 'new-grant', 'new-listing']) {
      mounted.draft = draft;
      render({ ...props, scopeKey, state: 'denied', current: undefined });
      expect(mounted.draft).toEqual({ amount: null, operation: null });
      expect(mounted.buttons.has(copy[locale].retry)).toBe(false);
    }
  }
});
