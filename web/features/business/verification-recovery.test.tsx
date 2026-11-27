import type { ReactElement, ReactNode } from 'react';
import { expect, it, vi } from 'vitest';
import { DecisionHistory, type Decision } from './history';
const state = vi.hoisted(() => ({ slots: [] as unknown[], index: 0, request: vi.fn(), file: vi.fn(),
  evidence: { data: { items: [] as { id: string; kind: 'identity' | 'possession'; size: number }[] }, isError: false, error: null as Error | null, isPending: false, refetch: vi.fn() },
  detail: { data: { application_id: 'private-application', revision: 3, application_revision: 2, history: [] as Decision[], history_total: 0 }, isError: false, error: null as Error | null, isPending: false, refetch: vi.fn() } }));
vi.mock('react', async original => ({ ...await original<typeof import('react')>(), useEffect: () => {},
  useState: (initial: unknown) => { const i = state.index++; if (!(i in state.slots)) state.slots[i] = initial;
    return [state.slots[i], (next: unknown) => { state.slots[i] = typeof next === 'function' ? next(state.slots[i]) : next; }]; },
}));
vi.mock('./reads', () => ({ reviewQueueRead: vi.fn(), useBusinessRead: ({queryKey}: {queryKey: string[]}) =>
  queryKey[1] === 'review' ? state.detail : queryKey[1] === 'evidence' ? state.evidence : {data: {items: [{id:'test-review',state:'pending'}], total:1, page:1, page_size:25}, refetch:vi.fn()} }));
vi.mock('./transport', () => ({ businessRequest: state.request, businessFile: state.file }));
vi.mock('@/shell/access-context', () => ({useAccessContext: () => ({fingerprint:'test-access'})}));
vi.mock('@/features/identity/session', () => ({useSession: () => ({principal:{permissions:['identity.private-seller.assign']}})}));
vi.mock('@/shell/locale-context', () => ({useLocale: () => 'en'}));
import { ApiError } from '@/lib/api/client';
import VerificationDesk from './verification';
import { CommandForm, PendingRecovery } from './command-form';
import { BusinessOperation } from './operation-v2';
import { PageControls } from './pagination';
function elements(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!node || typeof node !== 'object' || !('props' in node)) return [];
  const element = node as ReactElement<Record<string, unknown>>;
  return [element, ...elements(element.props.children as ReactNode)];
}
it('holds the original verdict through lost response and newer reads until identical recovery', async () => {
  const render = () => {state.index=0; return elements(VerificationDesk());};
  const open = render().find(node => typeof node.props.onClick === 'function' && node.props.variant === 'outline')!;
  (open.props.onClick as () => void)();
  const editor = render().find(node => node.type === CommandForm)!;
  const operation = new BusinessOperation();
  const data = new FormData(); data.set('application_revision','2'); data.set('state','approved'); data.set('reason','Private proof checked');
  (editor.props.onPending as (pending:boolean,id:string)=>void)(true, operation.id);
  state.request.mockRejectedValueOnce(new TypeError('Response unavailable'));
  await expect((editor.props.submit as Parameters<typeof CommandForm>[0]['submit'])(data,operation)).rejects.toThrow();
  const original = state.request.mock.calls[0];
  state.detail.data = {...state.detail.data, revision:4};
  const held = render();
  expect(held.find(node => node.type === CommandForm)?.key).toBe(editor.key);
  expect(held.find(node => node.type === PageControls)?.props.disabled).toBe(true);
  expect(held.find(node => node.props.variant === 'outline')?.props.disabled).toBe(true);
  state.request.mockResolvedValue({revision:4,state:'approved'});
  await expect(operation.recover()).resolves.toMatchObject({operation_state:'committed'});
  expect(state.request.mock.calls[1]).toEqual(original);
});

it.each(['assign', 'reassign'])('freezes %s and recovers the identical request after response loss', async kind => {
  state.slots = []; state.request.mockReset();
  const render = () => { state.index = 0; return elements(VerificationDesk()); };
  const forms = render().filter(node => node.type === CommandForm);
  const editor = forms[kind === 'assign' ? 0 : 1];
  const operation = new BusinessOperation();
  const data = new FormData();
  data.set('application', 'test-application'); data.set('review', 'test-review');
  data.set('revision', '3'); data.set('reviewer', 'test-reviewer'); data.set('reason', 'Independent review assignment');
  (editor.props.onPending as (pending:boolean,id:string)=>void)(true, operation.id);
  state.request.mockRejectedValueOnce(new TypeError('Response unavailable'));
  await expect((editor.props.submit as Parameters<typeof CommandForm>[0]['submit'])(data, operation)).rejects.toThrow();
  const original = state.request.mock.calls[0];
  const held = render();
  expect(held.filter(node => node.type === CommandForm).every(node => node.props.disabled)).toBe(true);
  expect(held.find(node => node.type === PageControls)?.props.disabled).toBe(true);
  expect(original[0]).toBe(kind === 'assign' ? '/v1/private-reviews' : '/v1/private-reviews/test-review/reassign');
  state.request.mockResolvedValue({ revision: 4, state: 'pending' });
  await expect(operation.recover()).resolves.toMatchObject({ operation_state: 'committed', operation_id: operation.id });
  expect(state.request.mock.calls[1]).toEqual(original);
});


it.each([401, 403])('removes denied review history and evidence during recovery %i without changing the action reference', async status => {
  const { ApiError } = await import('@/lib/api/client');
  const { PendingRecovery } = await import('./command-form');
  state.slots = []; state.request.mockReset(); state.detail.isError = false; state.detail.error = null;
  const render = () => { state.index = 0; return elements(VerificationDesk()); };
  const open = render().find(node => typeof node.props.onClick === 'function' && node.props.variant === 'outline')!;
  (open.props.onClick as () => void)();
  const editor = render().find(node => node.type === CommandForm)!;
  const operation = new BusinessOperation();
  const data = new FormData(); data.set('application_revision', '2'); data.set('state', 'approved'); data.set('reason', 'Private proof checked');
  (editor.props.onPending as (pending: boolean, id: string, operation: BusinessOperation) => void)(true, operation.id, operation);
  state.request.mockRejectedValueOnce(new TypeError('Response unavailable'));
  await expect((editor.props.submit as Parameters<typeof CommandForm>[0]['submit'])(data, operation)).rejects.toThrow();
  const original = state.request.mock.calls[0];
  state.detail.isError = true; state.detail.error = new ApiError(status, 'denied', '');
  const denied = render();
  expect(denied.some(node => node.type === CommandForm && node.key === editor.key)).toBe(false);
  const recovery = denied.find(node => node.type === PendingRecovery)!;
  expect((recovery.props.recovery as Map<string, BusinessOperation>).get(operation.id)).toBe(operation);
  state.detail.error = new TypeError('Unavailable');
  expect(render().some(node => node.type === CommandForm && node.key === editor.key)).toBe(false);
  state.request.mockResolvedValue({revision: 4, state: 'approved'});
  await operation.recover();
  expect(state.request.mock.calls[1]).toEqual(original);
  state.detail.isError = false; state.detail.error = null;
});

it.each([new TypeError('Unavailable'), new ApiError(403, 'denied', '')])('shows failed evidence and retries the detail reads', async error => {
  state.slots = []; state.detail.isError = false; state.detail.error = null;
  state.evidence.isError = true; state.evidence.error = error;
  state.detail.refetch.mockResolvedValue({ isError: false });
  state.evidence.refetch.mockResolvedValue({ isError: false });
  const render = () => { state.index = 0; return elements(VerificationDesk()); };
  const open = render().find(node => node.props.variant === 'outline')!;
  (open.props.onClick as () => void)();
  const nodes = render();
  expect(nodes.some(node => node.props.error === error)).toBe(true);
  expect(nodes.some(node => node.type === CommandForm && node.key === 'test-review:4')).toBe(false);
  const retry = nodes.find(node => node.props.children === 'Try again' && typeof node.props.onClick === 'function')!;
  (retry.props.onClick as () => void)();
  await Promise.resolve();
  expect(state.evidence.refetch).toHaveBeenCalled();
  expect(state.detail.refetch).toHaveBeenCalled();
  state.evidence.isError = false; state.evidence.error = null;
});

it.each([
  { status: 401, pending: false }, { status: 403, pending: false },
  { status: 401, pending: true }, { status: 403, pending: true },
])('clears mounted private details on download denial $status with pending verdict $pending', async ({ status, pending }) => {
  state.slots = []; state.request.mockReset(); state.file.mockReset();
  state.detail.isError = false; state.detail.error = null;
  state.detail.data = { application_id: 'private-application', revision: 3, application_revision: 2,
    history: [{ revision: 2, state: 'approved', reason: 'Private review reason', created_at: '2026-11-17' }], history_total: 1 };
  state.evidence.isError = false; state.evidence.error = null;
  state.evidence.data = { items: [{ id: 'private-evidence', kind: 'identity', size: 12 }] };
  const render = () => { state.index = 0; return elements(VerificationDesk()); };
  (render().find(node => node.props.variant === 'outline')!.props.onClick as () => void)();
  const initial = render();
  const editor = initial.find(node => node.type === CommandForm)!;
  expect(initial.some(node => node.type === DecisionHistory)).toBe(true);
  expect(initial.some(node => node.props.children === 'private-application')).toBe(true);
  const operation = new BusinessOperation();
  if (pending) {
    const data = new FormData(); data.set('application_revision', '2'); data.set('state', 'approved'); data.set('reason', 'Private proof checked');
    (editor.props.onPending as (pending: boolean, id: string, operation: BusinessOperation) => void)(true, operation.id, operation);
    state.request.mockRejectedValueOnce(new TypeError('Response unavailable'));
    await expect((editor.props.submit as Parameters<typeof CommandForm>[0]['submit'])(data, operation)).rejects.toThrow();
  }
  const original = state.request.mock.calls[0];
  const error = new ApiError(status, 'denied', '');
  state.file.mockRejectedValueOnce(error);
  (render().find(node => node.props.children === 'Download private evidence')!.props.onClick as () => void)();
  await vi.waitFor(() => expect(render().some(node => node.props.error === error)).toBe(true));
  expect(state.file).toHaveBeenCalledWith('/v1/private-reviews/test-review/files/private-evidence', null);
  const denied = render();
  expect(denied.some(node => node.type === CommandForm && node.key === editor.key)).toBe(false);
  expect(denied.some(node => node.type === DecisionHistory)).toBe(false);
  expect(denied.some(node => node.props.children === 'private-application')).toBe(false);
  expect(denied.some(node => node.props.children === 'Identity evidence')).toBe(false);
  expect(denied.some(node => node.props.children === 'Download private evidence')).toBe(false);
  expect(denied.some(node => node.type === PendingRecovery)).toBe(pending);
  if (pending) {
    const recovery = denied.find(node => node.type === PendingRecovery)!;
    expect([...(recovery.props.recovery as Map<string, BusinessOperation>).keys()]).toEqual([operation.id]);
    expect((recovery.props.recovery as Map<string, BusinessOperation>).get(operation.id)).toBe(operation);
    state.request.mockResolvedValue({ revision: 4, state: 'approved' });
    await expect(operation.recover()).resolves.toMatchObject({ operation_state: 'committed', operation_id: operation.id });
    expect(state.request.mock.calls[1]).toEqual(original);
  }
});
