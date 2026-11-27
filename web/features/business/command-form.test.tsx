import type { ReactElement, ReactNode } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
const harness = vi.hoisted(() => ({
  effects: [] as (() => void | (() => void))[], slots: [] as unknown[], index: 0, pending: false, running: Promise.resolve(),
  operation: { id: 'test-operation', recover: vi.fn(), dispose: vi.fn(), retainSubmission: vi.fn(), replay: vi.fn() },
}));
vi.mock('react', async importOriginal => ({
  ...await importOriginal<typeof import('react')>(),
  useState: (initial: unknown) => {
    const index = harness.index++, slots = harness.slots;
    if (!(index in slots)) slots[index] = initial;
    return [slots[index], (next: unknown) => { slots[index] = typeof next === 'function' ? next(slots[index]) : next; }];
  },
  useRef: (initial: unknown) => {
    const index = harness.index++;
    if (!(index in harness.slots)) harness.slots[index] = { current: initial };
    return harness.slots[index];
  },
  useEffect: (effect: () => void | (() => void)) => { harness.effects.push(effect); },
}));
vi.mock('@beirut-time/ui/foundation', () => ({ Button: 'button', State: 'output' }));
vi.mock('./operation-v2', () => ({ BusinessOperation: class { constructor() { return { ...harness.operation, id: crypto.randomUUID() }; } } }));
vi.mock('./components', () => ({
  Feedback: 'output',
  useCopy: () => ({ save: 'Save', newAction: 'New action', retry: 'Retry', recoverAction: 'Recover' }),
  useAction: () => ({ pending: harness.pending, error: null, run: (invoke: () => Promise<void>) => {
    harness.pending = true;
    harness.running = invoke().catch(() => {}).finally(() => { harness.pending = false; });
    return harness.running;
  } }),
}));
import { ApiError } from '@/lib/api/client';
import { CommandForm, PendingRecovery, usePendingCommands } from './command-form';

function elements(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!node || typeof node !== 'object' || !('props' in node)) return [];
  const element = node as ReactElement<Record<string, unknown>>;
  return [element, ...elements(element.props.children as ReactNode)];
}
beforeEach(() => {
  harness.effects = []; harness.slots = []; harness.pending = false; harness.index = 0;
  harness.operation.recover.mockReset(); harness.operation.dispose.mockReset(); harness.operation.replay.mockReset();
  const NativeFormData = globalThis.FormData;
  vi.stubGlobal('FormData', class extends NativeFormData { constructor() { super(); } });
});

it.each(['retry', 'recover'])('protects the original reference when %s after rejection becomes uncertain', async mode => {
  const submit = vi.fn().mockRejectedValueOnce(new ApiError(409, 'stale_revision', ''));
  const onPending = vi.fn(), onComplete = vi.fn();
  const render = () => {
    harness.index = 0;
    return elements(CommandForm({ children: null, submit, onPending, onComplete }));
  };
  const button = (nodes: ReturnType<typeof render>, label: string) => nodes.find(node => node.type === 'button' && node.props.children === label)!;
  const form = render().find(node => node.type === 'form')!;
  (form.props.onSubmit as (event: unknown) => void)({ preventDefault() {}, currentTarget: {} });
  await harness.running;
  const reset = button(render(), 'New action');
  expect(reset).toBeDefined();
  expect(onPending).toHaveBeenLastCalledWith(false, expect.any(String));
  let fail!: (error: unknown) => void;
  const uncertain = new Promise<never>((_, reject) => { fail = reject; });
  if (mode === 'retry') submit.mockReturnValueOnce(uncertain);
  else harness.operation.recover.mockReturnValueOnce(uncertain);
  (button(render(), mode === 'retry' ? 'Retry' : 'Recover').props.onClick as () => void)();
  expect(onPending).toHaveBeenLastCalledWith(true, expect.any(String), expect.any(Object));
  (reset.props.onClick as () => void)();
  expect(harness.operation.dispose).not.toHaveBeenCalled();
  expect(button(render(), 'New action')).toBeUndefined();
  fail(new TypeError('Response unavailable'));
  await harness.running;
  expect(button(render(), 'New action')).toBeUndefined();
  expect(onPending).toHaveBeenLastCalledWith(true, expect.any(String), expect.any(Object));
  expect(harness.operation.dispose).not.toHaveBeenCalled();
  if (mode === 'retry') expect(submit.mock.calls[1]).toEqual(submit.mock.calls[0]);
});


it('keeps the second form pending when a rejected first form tries recovery, retry or reset', async () => {
  const workspace: unknown[] = [], first: unknown[] = [], second: unknown[] = [];
  const mount = <T,>(slots: unknown[], render: () => T) => {
    harness.slots = slots; harness.index = 0;
    return render();
  };
  const pending = () => mount(workspace, usePendingCommands);
  const onComplete = vi.fn();
  const rejected = vi.fn().mockRejectedValue(new ApiError(409, 'stale_revision', ''));
  const uncertain = vi.fn().mockRejectedValue(new TypeError('Response unavailable'));
  // Keep workspace hooks outside each form's hook slots.
  const form = (slots: unknown[], submit: typeof rejected) => {
    const state = pending();
    return mount(slots, () => elements(CommandForm({children:null,submit,onComplete,disabled:state.busy,onPending:state.onPending})));
  };
  const button = (nodes: ReturnType<typeof form>, label: string) => nodes.find(node => node.type === 'button' && node.props.children === label)!;
  const start = (nodes: ReturnType<typeof form>) => (nodes.find(node => node.type === 'form')!.props.onSubmit as (event: unknown) => void)({preventDefault() {},currentTarget:{}});
  start(form(first, rejected)); await harness.running;
  expect(pending().busy).toBe(false);
  start(form(second, uncertain)); await harness.running;
  expect(pending().busy).toBe(true);
  const completed = onComplete.mock.calls.length;
  const held = form(first, rejected);
  for (const label of ['Recover', 'Retry', 'New action']) {
    const control = button(held, label);
    expect(control.props.disabled).toBe(true);
    (control.props.onClick as () => void)();
  }
  expect(rejected).toHaveBeenCalledTimes(1);
  expect(harness.operation.recover).not.toHaveBeenCalled();
  expect(harness.operation.dispose).not.toHaveBeenCalled();
  expect(onComplete).toHaveBeenCalledTimes(completed);
  expect(pending().busy).toBe(true);
  // Even a duplicate release from the first operation cannot release the second.
  pending().onPending(false, 'test-other-operation');
  expect(pending().busy).toBe(true);
  const owner = form(second, uncertain);
  expect(button(owner, 'Retry').props.disabled).toBe(false);
  (button(owner, 'Retry').props.onClick as () => void)(); await harness.running;
  expect(uncertain.mock.calls[1]).toEqual(uncertain.mock.calls[0]);
  expect(pending().busy).toBe(true);
});

it('retains command source identity through failed and newer reads until resolution, clearing on access change', async () => {
  const { useCommandSnapshot } = await import('./command-form');
  const original = { revision: 3, can_submit: true, challenge_id: 'test-challenge' };
  const newer = { revision: 4, can_submit: false, challenge_id: 'test-next-challenge' };
  const useSnapshot = (value: typeof original | undefined, pending: boolean, scope = 'test-access') => {
    harness.index = 0;
    return useCommandSnapshot(value, pending, scope);
  };
  expect(useSnapshot(original, false)).toBe(original);
  expect(useSnapshot(undefined, true)).toBe(original);
  expect(useSnapshot(newer, true)).toBe(original);
  expect(useSnapshot(undefined, true)).toBe(original);
  expect(useSnapshot(newer, false)).toBe(newer);
  expect(useSnapshot(newer, true)).toBe(newer);
  expect(useSnapshot(undefined, true, 'test-revoked-access')).toBeUndefined();
  expect(useSnapshot(undefined, true, 'test-revoked-access')).toBeUndefined();
});


it.each([401, 403])('clears a pending private snapshot immediately on denial %i and does not restore it on timeout', async status => {
  const { useCommandSnapshot } = await import('./command-form');
  const original = { revision: 3, private_record: 'Restricted history' };
  const useSnapshot = (value: typeof original | undefined, error?: unknown) => {
    harness.index = 0;
    return useCommandSnapshot(value, true, 'test-access', error instanceof ApiError && [401, 403].includes(error.status));
  };
  expect(useSnapshot(original)).toBe(original);
  expect(useSnapshot(undefined, new ApiError(status, 'denied', ''))).toBeUndefined();
  expect(useSnapshot(undefined, new TypeError('Unavailable'))).toBeUndefined();
});


it('keeps the original recovery reference after permission denial without rendering private facts', async () => {
  const { BusinessOperation } = await import('./operation-v2');
  const operation = new BusinessOperation();
  const recovery = new Map([[operation.id, operation]]);
  const onPending = vi.fn(), refresh = vi.fn();
  const render = () => elements(PendingRecovery({ recovery, onPending, refresh }));
  harness.operation.recover.mockRejectedValueOnce(new ApiError(403, 'denied', ''));
  const recover = () => (render().find(node => node.type === 'button')!.props.onClick as () => void)();
  recover(); await harness.running;
  expect(onPending).not.toHaveBeenCalled();
  expect(harness.operation.dispose).not.toHaveBeenCalled();
  expect(recovery.get(operation.id)).toBe(operation);
  harness.operation.recover.mockResolvedValueOnce({ operation_state: 'committed' });
  recover(); await harness.running;
  expect(onPending).toHaveBeenCalledWith(false, operation.id);
  expect(refresh).toHaveBeenCalledOnce();
});


it('keeps transferred possession recovery alive when its denied detail unmounts', () => {
  const operation = harness.operation as unknown as import('./operation-v2').BusinessOperation;
  const mount = (owns: boolean) => Reflect.apply(usePendingCommands, null, [owns]) as ReturnType<typeof usePendingCommands>;
  const child = mount(false);
  child.onPending(true, operation.id, operation);
  const cleanup = harness.effects[0]();
  if (cleanup) cleanup();
  expect(harness.operation.dispose).not.toHaveBeenCalled();
  harness.slots = []; harness.index = 0; harness.effects = [];
  const workspace = mount(true);
  workspace.onPending(true, operation.id, operation);
  const dispose = harness.effects[0]();
  if (dispose) dispose();
  expect(harness.operation.dispose).toHaveBeenCalledOnce();
});

it('offers complete replay after detached lookup returns missing', async () => {
  const operation = harness.operation as unknown as import('./operation-v2').BusinessOperation;
  const recovery = new Map([[operation.id, operation]]);
  const onPending = vi.fn(), refresh = vi.fn();
  harness.operation.replay.mockResolvedValueOnce({operation_state:'committed'});
  const nodes = elements(PendingRecovery({recovery,onPending,refresh}));
  const retry = nodes.find(node => node.type === 'button' && node.props.children === 'Retry')!;
  (retry.props.onClick as () => void)();
  await harness.running;
  expect(harness.operation.replay).toHaveBeenCalledOnce();
  expect(onPending).toHaveBeenCalledWith(false, operation.id);
  expect(refresh).toHaveBeenCalledOnce();
});

it.each(['recover', 'retry'])('retains an uncertain command after %s permission denial until authorized recovery', async mode => {
  const submit = vi.fn().mockRejectedValueOnce(new TypeError('Response unavailable'));
  const onPending = vi.fn(), onComplete = vi.fn();
  const render = () => {
    harness.index = 0;
    return elements(CommandForm({ children: null, submit, onPending, onComplete }));
  };
  const button = (label: string) => render().find(node => node.type === 'button' && node.props.children === label);
  const form = render().find(node => node.type === 'form')!;
  (form.props.onSubmit as (event: unknown) => void)({ preventDefault() {}, currentTarget: {} });
  await harness.running;
  const reference = onPending.mock.calls[0][1];
  const original = submit.mock.calls[0];
  if (mode === 'recover') harness.operation.recover.mockRejectedValueOnce(new ApiError(403, 'denied', ''));
  else submit.mockRejectedValueOnce(new ApiError(403, 'denied', ''));
  (button(mode === 'recover' ? 'Recover' : 'Retry')!.props.onClick as () => void)();
  await harness.running;
  expect(onPending.mock.calls.every(([pending, id]) => pending && id === reference)).toBe(true);
  expect(button('New action')).toBeUndefined();
  expect(onComplete).not.toHaveBeenCalled();
  expect(harness.operation.dispose).not.toHaveBeenCalled();
  harness.operation.recover.mockResolvedValueOnce({ operation_state: 'committed', state: 'active', revision: 1 });
  (button('Recover')!.props.onClick as () => void)();
  await harness.running;
  expect(onPending).toHaveBeenLastCalledWith(false, reference);
  expect(onComplete).toHaveBeenCalledOnce();
  expect(button('New action')).toBeDefined();
  if (mode === 'retry') expect(submit.mock.calls[1]).toEqual(original);
  expect(new Set(onPending.mock.calls.map(([, id]) => id))).toEqual(new Set([reference]));
});
