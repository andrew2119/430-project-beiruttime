import type { ReactElement, ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const hooks = vi.hoisted(() => ({
  slots: [] as unknown[], cursor: 0, changed: false,
  fingerprint: 'current-access', locale: 'en' as 'en' | 'ar',
}));
vi.mock('react', async importOriginal => ({
  ...await importOriginal<typeof import('react')>(),
  useState: (initial: unknown) => {
    const index = hooks.cursor++;
    if (!(index in hooks.slots)) hooks.slots[index] = initial;
    return [hooks.slots[index], (value: unknown) => { hooks.slots[index] = value; hooks.changed = true; }];
  },
  useRef: (initial: unknown) => {
    const index = hooks.cursor++;
    if (!(index in hooks.slots)) hooks.slots[index] = { current: initial };
    return hooks.slots[index];
  },
  useEffect: () => {},
}));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => hooks.locale }));
vi.mock('@/features/identity/session', () => ({ useSession: () => ({ access_fingerprint: hooks.fingerprint }) }));
import AuctionExceptions, { type Connection } from './view';

// Exercise component state and keyed reconciliation without a browser environment.
function mounted() {
  const parent: unknown[] = [];
  let child: unknown[] = [];
  let key: string | null = null;
  return (props: Parameters<typeof AuctionExceptions>[0]) => {
    let element: ReturnType<typeof AuctionExceptions>;
    do {
      hooks.slots = parent; hooks.cursor = 0; hooks.changed = false;
      element = AuctionExceptions(props);
    } while (hooks.changed);
    if (element.key !== key) { child = []; key = element.key; }
    hooks.slots = child; hooks.cursor = 0;
    return (element.type as (props: unknown) => ReactElement)(element.props);
  };
}
function find(node: ReactNode, predicate: (element: ReactElement<Record<string, unknown>>) => boolean): ReactElement<Record<string, unknown>> | undefined {
  if (Array.isArray(node)) {
    for (const item of node) { const found = find(item, predicate); if (found) return found; }
  } else if (node && typeof node === 'object' && 'props' in node) {
    const element = node as ReactElement<Record<string, unknown>>;
    return predicate(element) ? element : find(element.props.children as ReactNode, predicate);
  }
}
const context: Connection['context'] = { subject_id:'auction', watch_id:'watch', actor_id:'operator', organization_id:'business', expected_revision:4, quote_id:'quote', quote_revision:2, policy_revision:1, assignment_revision:3 };
afterEach(() => { vi.useRealTimers(); hooks.fingerprint = 'current-access'; hooks.locale = 'en'; });
describe('private operation lifecycle', () => {
  it.each(['🔒'.repeat(1500), 'a' + '🔒'.repeat(1000), '🔒'.repeat(2000), '🔒'.repeat(2001)])('preserves the exact reason field input (%#)', value => {
    const render = mounted();
    const connection: Connection = {context, submit:vi.fn()};
    let tree = render({connection, access:'ready'});
    (find(tree, element => element.props.label === 'Private reason')!.props.onValueChange as (value: string) => void)(value);
    tree = render({connection, access:'ready'});
    expect(find(tree, element => element.props.label === 'Private reason')?.props.value).toBe(value);
    expect(find(tree, element => element.props.type === 'submit')?.props.disabled).toBe(Array.from(value).length > 2000);
    hooks.locale = 'ar';
    tree = render({connection, access:'ready'});
    expect(find(tree, element => element.props.label === 'السبب الخاص')?.props.value).toBe(value);
    expect(connection.submit).not.toHaveBeenCalled();
  });
  it('retries the identical timed-out command after temporary availability and locale changes', async () => {
    vi.useFakeTimers();
    const submit = vi.fn<Connection['submit']>(() => new Promise<never>(() => {}));
    const connection = { context, submit };
    const render = mounted();
    let tree = render({ connection, access:'ready' });
    const reason = find(tree, element => element.props.label === 'Private reason')!;
    (reason.props.onValueChange as (value: string) => void)('سبب خاص mixed 🔒 reason');
    tree = render({ connection, access:'ready' });
    const pending = (find(tree, element => element.type === 'form')!.props.onSubmit as (event: {preventDefault(): void}) => Promise<void>)({preventDefault() {}});
    await vi.advanceTimersByTimeAsync(5000);
    await pending;
    const original = submit.mock.calls[0][0];
    for (const access of ['loading', 'unavailable'] as const) {
      tree = render({ access });
      expect(find(tree, element => element.type === 'form')).toBeUndefined();
    }
    hooks.locale = 'ar';
    tree = render({ connection:{...connection, context:{...context, expected_revision:5}}, access:'ready' });
    expect(find(tree, element => element.props.label === 'السبب الخاص')?.props.value).toBe(original.reason);
    const retry = (find(tree, element => element.type === 'form')!.props.onSubmit as (event: {preventDefault(): void}) => Promise<void>)({preventDefault() {}});
    expect(submit.mock.calls[1][0]).toBe(original);
    await vi.advanceTimersByTimeAsync(5000);
    await retry;
  });
  it.each(['denied', 'empty', 'identity', 'record', 'assignment'] as const)('clears private drafts on %s change', change => {
    const render = mounted();
    const connection: Connection = {context, submit:vi.fn()};
    let tree = render({connection, access:'ready'});
    (find(tree, element => element.props.label === 'Private reason')!.props.onValueChange as (value: string) => void)('Private recorded reason');
    if (change === 'denied' || change === 'empty') render({connection, access:change});
    if (change === 'identity') hooks.fingerprint = 'other-access';
    const next = change === 'record' ? {...context, subject_id:'other'} : change === 'assignment' ? {...context, assignment_revision:4} : context;
    tree = render({connection:{...connection, context:next}, access:'ready'});
    expect(find(tree, element => element.props.label === 'Private reason')?.props.value).toBe('');
  });
});
