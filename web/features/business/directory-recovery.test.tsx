import type { ReactElement, ReactNode } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
import type { OfficialBusiness } from '@contracts/contracts-identity/businesses';
import type { Page } from '@contracts/contracts-identity/businesses/workspace_v2';
const state = vi.hoisted(() => ({
  slots: [] as unknown[], index: 0, scope: 'test-access',
  query: { data: undefined as Page<OfficialBusiness> | undefined, isError: false, isPending: false, isFetching: false, error: null as Error | null, refetch: vi.fn() },
  request: vi.fn(),
}));
vi.mock('react', async original => ({
  ...await original<typeof import('react')>(), useEffect: () => {},
  useState: (initial: unknown) => {
    const index = state.index++;
    if (!(index in state.slots)) state.slots[index] = initial;
    return [state.slots[index], (next: unknown) => {
      state.slots[index] = typeof next === 'function' ? next(state.slots[index]) : next;
    }];
  },
}));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => 'en' }));
vi.mock('./reads', () => ({ directoryRead: vi.fn(), useBusinessRead: () => state.query }));
vi.mock('./drafts', () => ({ usePublicBusinessDraft: () => ({ attachForm: vi.fn(), save: vi.fn(), clear: vi.fn() }) }));
vi.mock('next/navigation', () => ({ usePathname: () => '/business' }));
vi.mock('./transport', () => ({ businessRequest: state.request }));
vi.mock('@/shell/access-context', () => ({ useAccessContext: () => ({ fingerprint: state.scope }) }));
vi.mock('@/features/identity/session', () => ({ useSession: () => ({ principal: { permissions: ['identity.businesses.manage'] } }) }));
import { CommandForm } from './command-form';
import BusinessDirectory from './directory';
import { BusinessOperation } from './operation-v2';

function elements(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!node || typeof node !== 'object' || !('props' in node)) return [];
  const element = node as ReactElement<Record<string, unknown>>;
  return [element, ...elements(element.props.children as ReactNode)];
}
const member: OfficialBusiness = { id: 'test-member', public_name: 'Synthetic business', kind: 'brand', capabilities: ['sales'], state: 'active', revision: 3, sample: true, platform_onboarded: true, authenticated_business: true, independent_watch_authentication_required: false };
const answer = (revision: number): Page<OfficialBusiness> => ({ items: [{ ...member, revision }], total: 1, page: 1, page_size: 25 });
const render = () => { state.index = 0; return elements(BusinessDirectory()); };
const editor = (nodes: ReturnType<typeof render>) => nodes.find(node => node.type === CommandForm)!;
beforeEach(() => {
  state.slots = []; state.scope = 'test-access'; state.query.data = answer(3); state.query.isError = false; state.query.error = null;
  state.request.mockReset();
});
it.each(['failed', 'newer'])('retains the unresolved editor and exact recovery request through a %s refresh', async refresh => {
  const initial = render(), form = editor(initial);
  const card = initial.find(node => node.key === 'test-member:3')!;
  const pending = form.props.onPending as (value: boolean, id: string) => void;
  const operation = new BusinessOperation();
  const data = new FormData();
  data.set('state', 'active'); data.set('scope', 'Current scope'); data.set('reason', 'Current staff update');
  data.append('capabilities', 'business.records.read');
  state.request.mockRejectedValueOnce(new TypeError('Response unavailable'));
  pending(true, operation.id);
  const submit = form.props.submit as Parameters<typeof CommandForm>[0]['submit'];
  await expect(submit(data, operation)).rejects.toThrow('Response unavailable');
  const original = state.request.mock.calls[0];
  state.query.data = refresh === 'failed' ? undefined : answer(4);
  state.query.isError = refresh === 'failed';
  const retained = render();
  expect(retained.find(node => node.key === card.key)?.type).toBe(card.type);
  expect(retained.some(node => node.key === 'test-member:4')).toBe(false);
  expect(editor(retained).type).toBe(form.type);
  expect(editor(retained).props.disabled).toBe(true);
  state.request.mockResolvedValue({ revision: 4, state: 'active' });
  await expect(operation.recover()).resolves.toMatchObject({ operation_id: operation.id, operation_state: 'committed' });
  expect(state.request.mock.calls[1]).toEqual(original);
  pending(false, operation.id);
  const resolved = render();
  expect(resolved.some(node => node.key === card.key)).toBe(false);
  if (refresh === 'newer') expect(resolved.some(node => node.key === 'test-member:4')).toBe(true);
});
it('clears retained private editors when access changes', () => {
  const form = editor(render());
  (form.props.onPending as (value: boolean, id: string) => void)(true, 'test-operation');
  render();
  state.scope = 'test-revoked-access'; state.query.data = undefined; state.query.isError = true;
  expect(render().some(node => node.key === 'test-member:3')).toBe(false);
});


it.each([401, 403])('clears denied private records during an unresolved command %i', async status => {
  const { ApiError } = await import('@/lib/api/client');
  const form = editor(render());
  (form.props.onPending as (value: boolean, id: string) => void)(true, 'test-operation');
  state.query.isError = true; state.query.error = new ApiError(status, 'denied', '');
  expect(render().some(node => node.key === 'test-member:3')).toBe(false);
  state.query.data = undefined; state.query.error = new TypeError('Unavailable');
  expect(render().some(node => node.key === 'test-member:3')).toBe(false);
});
