import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';

let signedIn = false;
vi.mock('next/navigation', () => ({usePathname: () => '/en/orders/order-1', useSearchParams: () => new URLSearchParams('organization_id=business-1')}));
vi.mock('@/shell/locale-context', () => ({useLocale: () => 'en'}));
vi.mock('@/features/identity/session', async importOriginal => {
  const original = await importOriginal<typeof import('../../../../web/features/identity/session')>();
  return {...original, useSession: () => signedIn ? {access_fingerprint: 'buyer'} : null};
});
import OrderTimeline from '../../../../web/features/order-timeline/view';

describe('root composition boundary', () => {
  it.each([false, true])('renders recovery without a shared read scope for session %s', active => {
    signedIn = active;
    const html = renderToStaticMarkup(createElement(OrderTimeline, {id: 'order-1'}));
    expect(html).toContain(active ? 'Order facts are unavailable' : 'Sign in to review your current orders');
    expect(html).not.toContain('BT-1001');
    if (active) expect(html).toContain('/orders/order-1?organization_id=business-1');
  });
});
