import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { isOrderPage, isTimeline } from '../../../../packages/contracts-comms/order-timeline';
import fixtures from '../../../../packages/contracts-comms/order-timeline/fixtures.json';
import { money } from '../../../../web/features/order-timeline/money';
import { copy } from '../../../../web/features/order-timeline/copy';

let locale: 'en' | 'ar' = 'en';
let canonical = true;
let signedIn = true;
let answer: unknown = fixtures.success;
let failure: unknown = null;
let pending = false;
let organization: string | null = null;
const readKeys: unknown[] = [];
vi.mock('@/shell/locale-context', () => ({useLocale: () => locale}));
vi.mock('next/navigation', () => ({usePathname: () => '/orders/order-1', useSearchParams: () => new URLSearchParams(organization ? {organization_id: organization} : {})}));
vi.mock('@/shell/foundation/path', () => ({usesFoundationShell: () => canonical}));
vi.mock('@/features/identity/session', () => ({useSession: () => signedIn ? ({access_fingerprint: 'buyer'}) : null, authenticatedRequest: vi.fn(), signInHref: (path: string, language: string) => `/${language}/sign-in?next=${encodeURIComponent(path)}`}));
vi.mock('@/lib/page-speed/read', () => ({usePageRead: (read: {key: unknown} | null) => { readKeys.push(read?.key); return ({data: answer, error: failure, isPending: pending, isFetching: false, refetch: vi.fn()}); }}));
vi.mock('@/lib/page-speed/arrival', () => ({AnswerArrival: ({children}: {children: React.ReactNode}) => children}));
import OrderTimeline from '../../../../web/features/order-timeline/view';
import { ApiError } from '../../../../web/lib/api/client';

const render = () => renderToStaticMarkup(createElement(OrderTimeline, {id: 'order-1'}));
describe('private timeline contracts', () => {
  it('accepts the deterministic pending fixture without inventing completion', () => {
    expect(isTimeline(fixtures.success)).toBe(true);
    expect(fixtures.success.milestones.every(row => row.state === 'pending')).toBe(true);
  });
  it.each([NaN, Infinity, -1, true, 9007199254740992])('rejects invalid money %s', amount => {
    expect(isTimeline({...fixtures.success, economics: {...fixtures.success.economics, total_minor: amount}})).toBe(false);
  });
  it('rejects missing, duplicate, reordered and unbound milestones', () => {
    expect(isTimeline({...fixtures.success, milestones: []})).toBe(false);
    expect(isTimeline({...fixtures.success, milestones: [...fixtures.success.milestones].reverse()})).toBe(false);
    expect(isTimeline({...fixtures.success, watch_id: null})).toBe(false);
    expect(isTimeline({...fixtures.success, simulated: false})).toBe(false);
  });
  it('rejects extra private fields at every response boundary', () => {
    expect(isTimeline({...fixtures.success, evidence_refs: ['private-file']})).toBe(false);
    expect(isTimeline({...fixtures.success, waiting: {...fixtures.success.waiting, private_notes: 'secret'}})).toBe(false);
    expect(isOrderPage({schema_version:'order-timeline-list.v1',items:[],total:0,offset:0,limit:20,evidence_refs:[]})).toBe(false);
  });
  it('preserves exact cents through the largest permitted amount', () => {
    expect(money(9007199254740991, 'en')).toBe('90,071,992,547,409.91 USD');
    expect(money(515000, 'en')).toBe('5,150.00 USD');
    expect(money(515000, 'ar')).toContain('٥٬١٥٠٫٠٠');
  });
  it.each([0,1,1000])('uses complete server page totals %s', total => {
    const items = Array.from({length: Math.min(20,total)},(_,i) => ({order_id: `order-${i}`,reference: `BT-${i}`}));
    expect(isOrderPage({schema_version:'order-timeline-list.v1',items,total,offset:0,limit:20})).toBe(true);
    if (total) expect(isOrderPage({schema_version:'order-timeline-list.v1',items:[],total,offset:0,limit:20})).toBe(false);
  });
  it.each(['en','ar'] as const)('renders amounts, waiting and safe recovery in %s', language => {
    locale = language; canonical = true; answer = fixtures.success; failure = null; pending = false;
    const html = render();
    expect(html).toContain(copy[language].waiting);
    expect(html).toContain(copy[language].pending);
    expect(html).not.toContain(copy[language].confirmed);
    expect(html).toContain('operator-1');
    failure = new ApiError(403,'denied','');
    expect(render()).toContain(copy[language].denied);
    expect(render()).not.toContain('BT-1001');
    failure = new ApiError(503,'unavailable','');
    expect(render()).toContain(copy[language].unavailable);
    expect(render()).not.toContain('BT-1001');
    failure = null; answer = undefined; pending = true;
    expect(render()).toContain(copy[language].loading);
    pending = false; canonical = false;
    expect(render()).toContain(copy[language].title);
  });
  it.each(['en','ar'] as const)('offers sign-in recovery for a closed session in %s', language => {
    locale = language; canonical = true; signedIn = false; failure = null; pending = false; answer = fixtures.success;
    expect(render()).toContain(copy[language].signIn);
    expect(render()).toContain('sign-in?next=');
    expect(render()).not.toContain('BT-1001');
    signedIn = true;
  });
  it('reads the current URL scope and preserves it across locale changes', () => {
    canonical = true; signedIn = true; pending = false; failure = null; answer = undefined;
    organization = 'business-1'; locale = 'en'; render();
    expect(readKeys.at(-1)).toEqual(['l22-order-timeline','order-1','business-1',0]);
    organization = 'business-2'; render();
    expect(readKeys.at(-1)).toEqual(['l22-order-timeline','order-1','business-2',0]);
    locale = 'ar'; render();
    expect(readKeys.at(-1)).toEqual(['l22-order-timeline','order-1','business-2',0]);
    organization = null; render();
    expect(readKeys.at(-1)).toEqual(['l22-order-timeline','order-1',null,0]);
  });
  it.each(['en','ar'] as const)('renders distinct financial states in %s', language => {
    locale = language; canonical = true; signedIn = true; pending = false; failure = null;
    answer = {...fixtures.success, financial: [fixtures.refund_pending]};
    expect(isTimeline(answer)).toBe(true);
    expect(render()).toContain(copy[language].refund);
    expect(render()).not.toContain(copy[language].confirmed);
    answer = {...fixtures.success, financial: [fixtures.refund_confirmed]};
    expect(render()).toContain(copy[language].confirmed);
    expect(render()).toContain('refund-operation-1');
  });
  it('accepts long mixed-script content only as text within bounded references', () => {
    expect(isOrderPage({schema_version:'order-timeline-list.v1',items:[{order_id:'order-1',reference:'ساعات Latin 👨‍👩‍👦'}],total:1,offset:0,limit:20})).toBe(false);
    expect(new Set(Object.keys(copy.en))).toEqual(new Set(Object.keys(copy.ar)));
  });
});
