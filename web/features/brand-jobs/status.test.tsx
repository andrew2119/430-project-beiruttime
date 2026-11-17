import { createElement, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';

vi.mock('@beirut-time/ui/foundation', () => ({
  Card: ({ children }: { children: ReactNode }) => createElement('section', null, children),
  State: ({ title, body, children }: { title: string; body: string; children: ReactNode }) =>
    createElement('div', null, title, body, children),
  Button: ({ children, onClick, disabled }: { children: ReactNode; onClick: () => void; disabled: boolean }) => {
    if (!disabled) onClick();
    return createElement('button', { disabled }, children);
  },
}));
import { BrandJobStatus } from './status';

it.each(['en', 'ar'] as const)('recovers before a receipt exists in %s', locale => {
  const retry = vi.fn();
  const markup = renderToStaticMarkup(<BrandJobStatus locale={locale} receipt={null}
    loading={false} unavailable operationId="retained-operation" onRetry={retry} />);
  expect(markup).toContain('retained-operation');
  expect(markup).toContain('<button');
  expect(markup).toContain(locale === 'en'
    ? 'Current authorization is unavailable. Retry with the same action reference.'
    : 'التفويض الحالي غير متاح. أعد المحاولة بمرجع الإجراء نفسه.');
  expect(retry).toHaveBeenCalledExactlyOnceWith('retained-operation');
});

it('keeps the action unavailable while checking', () => {
  const retry = vi.fn();
  const markup = renderToStaticMarkup(<BrandJobStatus locale="en" receipt={null}
    loading unavailable operationId="retained-operation" onRetry={retry} />);
  expect(markup).toContain('disabled');
  expect(retry).not.toHaveBeenCalled();
});
