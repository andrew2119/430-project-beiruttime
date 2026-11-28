import type { ReactElement, ReactNode } from 'react';
import { expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({ slots: [] as unknown[], index: 0, request: vi.fn(), running: Promise.resolve() }));
vi.mock('react', async original => ({
  ...await original<typeof import('react')>(),
  useState: (initial: unknown) => {
    const index = state.index++;
    if (!(index in state.slots)) state.slots[index] = initial;
    return [state.slots[index], (next: unknown) => { state.slots[index] = typeof next === 'function' ? next(state.slots[index]) : next; }];
  },
  useRef: (initial: unknown) => {
    const index = state.index++;
    if (!(index in state.slots)) state.slots[index] = { current: initial };
    return state.slots[index];
  },
}));
vi.mock('./transport', () => ({ businessRequest: state.request }));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => 'en' }));
vi.mock('./components', () => ({
  Feedback: 'output', useCopy: () => ({ earlierHistory: 'Older', serverTotal: 'Total' }),
  useAction: () => ({ pending: false, error: null, run: (invoke: () => Promise<void>) => {
    state.running = invoke().catch(() => {}); return state.running;
  } }),
}));
import { ApiError } from '@/lib/api/client';
import { DecisionHistory } from './history';
function elements(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!node || typeof node !== 'object' || !('props' in node)) return [];
  const element = node as ReactElement<Record<string, unknown>>;
  return [element, ...elements(element.props.children as ReactNode)];
}
it.each([401, 403])('clears private reasons and propagates history denial %i', async status => {
  state.slots = []; state.request.mockReset();
  const error = new ApiError(status, 'denied', '');
  state.request.mockRejectedValueOnce(error);
  const onDenied = vi.fn();
  const render = () => {
    state.index = 0;
    return elements(DecisionHistory({ reviewId: 'test-review', items: [{ revision: 2, state: 'approved', reason: 'Private reason', created_at: '2026-11-17' }], before: 2, total: 2, onDenied }));
  };
  const initial = render();
  expect(initial.some(node => node.props.children === 'Private reason')).toBe(true);
  (initial.find(node => typeof node.props.onClick === 'function')!.props.onClick as () => void)();
  await state.running;
  expect(onDenied).toHaveBeenCalledWith(error);
  expect(render().some(node => node.props.children === 'Private reason')).toBe(false);
  expect(render().some(node => node.props.error === error)).toBe(true);
});
