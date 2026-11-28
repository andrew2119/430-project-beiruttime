import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { ApiError } from '../../../../web/lib/api/client';
import { COPY } from '../../../../web/features/two-factor/copy';

const harness = vi.hoisted(() => ({
  values: [] as unknown[], cursor: 0, locale: 'en' as 'en' | 'ar', submit: vi.fn(), status: {data: {state: 'empty', revision: 0}, error: null as ApiError | null}, effects: [] as (()=>void)[],
}));
vi.mock('react', async importOriginal => ({
  ...await importOriginal<typeof import('react')>(),
  useState: (initial: unknown) => {
    const index = harness.cursor++;
    if (!(index in harness.values)) harness.values[index] = initial;
    return [harness.values[index], (value: unknown) => { harness.values[index] = value; }];
  },
  useRef: (initial: unknown) => {
    const index = harness.cursor++;
    if (!(index in harness.values)) harness.values[index] = {current: initial};
    return harness.values[index];
  },
  useEffect: (effect: ()=>void) => { harness.effects.push(effect); },
}));
vi.mock('@/shell/locale-context', () => ({useLocale: () => harness.locale}));
vi.mock('@/features/identity/session', () => ({useSession: () => ({access_fingerprint: 'test-scope'})}));
vi.mock('@/lib/page-speed/read', () => ({usePageRead: () => harness.status}));
vi.mock('@/shell/foundation/page', () => ({PageBody: 'body', PageFrame: 'layout', PageHeader: 'header'}));
vi.mock('@beirut-time/ui/foundation', () => ({Button: 'button', ButtonLink: 'a', Card: 'card', Input: 'input', State: 'state'}));
vi.mock('next/navigation', () => ({useRouter: () => ({refresh: vi.fn()})}));
vi.mock('@/features/two-factor/transport', () => ({statusRead: vi.fn(), submitFactor: harness.submit}));
import SecurityView from '../../../../web/features/two-factor/view';
import { SensitiveProofForm } from '../../../../web/features/two-factor/step-up';

type Node = ReactElement<Record<string, unknown>>;
function nodes(value: unknown): Node[] {
  if (Array.isArray(value)) return value.flatMap(nodes);
  if (!value || typeof value !== 'object' || !('props' in value)) return [];
  const node = value as Node;
  return [node, ...nodes(node.props.children)];
}
function mounted(kind: 'security' | 'proof') {
  const outer = kind === 'security' ? SecurityView({connected: true}) : SensitiveProofForm({
    scope: {action: 'seller_payout', record_id: 'test-record', record_revision: 1, organization_id: null, factor_revision: 2}, onProof: vi.fn(),
  });
  const form = nodes(outer).find(node => typeof node.type === 'function')!;
  return () => {
    harness.cursor = 0;
    const tree = (form.type as (props: Record<string, unknown>) => Node)(form.props);
    harness.effects.splice(0).forEach(effect=>effect());
    return tree;
  };
}
function enter(tree: Node, label: string, value: string) {
  const input = nodes(tree).find(node => node.props.label === label)!;
  (input.props.onValueChange as (value: string) => void)(value);
}
async function submit(tree: Node) {
  const form = nodes(tree).find(node => node.type === 'form')!;
  (form.props.onSubmit as (event: unknown) => void)({preventDefault() {}});
  await new Promise(resolve => setTimeout(resolve, 0));
}
beforeEach(() => {harness.values = []; harness.cursor = 0; harness.locale = 'en'; harness.submit.mockReset(); harness.effects = []; harness.status = {data: {state: 'empty', revision: 0}, error: null};});
describe('private state after current access denial', () => {
  for (const status of [401, 403]) for (const kind of ['security', 'proof'] as const) {
    it(`${kind} clears private state on ${status} and remains denied after language change`, async () => {
      const render = mounted(kind);
      if (kind === 'security') {
        enter(render(), COPY.en.password, 'test-password');
        harness.submit.mockResolvedValueOnce({state: 'enrolling', secret: 'test-private-secret', revision: 1});
        await submit(render());
      }
      enter(render(), kind === 'security' ? COPY.en.confirmCode : COPY.en.code, 'test-private-proof');
      harness.submit.mockRejectedValueOnce(new ApiError(status, 'denied', 'test-request'));
      await submit(render());
      expect(render().props.body).toBe(COPY.en.denied);
      expect(nodes(render()).some(node => node.type === 'form' || node.type === 'input')).toBe(false);
      expect(JSON.stringify(harness.values)).not.toMatch(/test-private|test-password|operation_id/);
      harness.locale = 'ar';
      expect(render().props.body).toBe(COPY.ar.denied);
      expect(harness.submit).toHaveBeenCalledTimes(kind === 'security' ? 2 : 1);
    });
  }
  for (const kind of ['security', 'proof'] as const) {
    it(`${kind} retains inputs on invalid proof and language change`, async () => {
      const render = mounted(kind);
      if (kind === 'security') {
        enter(render(), COPY.en.password, 'test-password');
        harness.submit.mockResolvedValueOnce({state: 'enrolling', secret: 'test-private-secret', revision: 1});
        await submit(render());
      }
      enter(render(), kind === 'security' ? COPY.en.confirmCode : COPY.en.code, 'test-private-proof');
      harness.submit.mockRejectedValueOnce(new ApiError(422, 'invalid_proof', 'test-request'));
      await submit(render());
      harness.locale = 'ar';
      expect(nodes(render()).some(node => node.props.value === 'test-private-proof')).toBe(true);
      if (kind === 'security') expect(nodes(render()).some(node => node.props.value === 'test-private-secret')).toBe(true);
    });
  }
});

for (const status of [401, 403]) it(`status refresh clears private state on ${status}`, async () => {
  const render = mounted('security');
  enter(render(), COPY.en.password, 'test-password');
  harness.submit.mockResolvedValueOnce({state: 'enrolling', secret: 'test-private-secret', revision: 1});
  await submit(render());
  expect(nodes(render()).some(node=>node.props.value === 'test-private-secret')).toBe(true);
  harness.status.error = new ApiError(status, 'denied', 'test-request');
  expect(render().props.body).toBe(COPY.en.denied);
  expect(JSON.stringify(harness.values)).not.toMatch(/test-private|test-password|operation_id/);
  harness.locale = 'ar';
  expect(render().props.body).toBe(COPY.ar.denied);
});
it('pending responses retain the same command across language change and retry', async () => {
  const render = mounted('security');
  enter(render(), COPY.en.password, 'test-password');
  harness.submit.mockResolvedValueOnce({state: 'pending', revision: 1});
  await submit(render());
  const original = harness.submit.mock.calls[0][0];
  expect(JSON.stringify(harness.values)).toContain(original.operation_id);
  harness.locale = 'ar';
  harness.submit.mockResolvedValueOnce({state: 'enrolling', secret: 'test-private-secret', revision: 1});
  await submit(render());
  expect(harness.submit.mock.calls[1][0]).toEqual(original);
  expect(nodes(render()).some(node=>node.props.value === 'test-private-secret')).toBe(true);
});
