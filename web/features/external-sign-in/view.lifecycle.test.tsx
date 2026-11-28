import type { ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';
import type { ExternalOperation } from '@contracts/contracts-identity/external-sign-in';
import type { Transport } from './controller';

const hooks = vi.hoisted(() => ({
  slots: [] as unknown[], cursor: 0, dirty: false,
  effects: [] as (() => void)[], locale: 'en',
}));
vi.mock('react', async original => ({
  ...await original<typeof import('react')>(),
  useState(initial: unknown) {
    const index = hooks.cursor++;
    if (!(index in hooks.slots)) hooks.slots[index] = typeof initial === 'function' ? initial() : initial;
    return [hooks.slots[index], (value: unknown) => {
      hooks.slots[index] = typeof value === 'function' ? value(hooks.slots[index]) : value;
      hooks.dirty = true;
    }];
  },
  useRef(initial: unknown) {
    const index = hooks.cursor++;
    if (!(index in hooks.slots)) hooks.slots[index] = {current: initial};
    return hooks.slots[index];
  },
  useEffect(effect: () => (() => void), dependencies: unknown[]) {
    const index = hooks.cursor++;
    const prior = hooks.slots[index] as {dependencies: unknown[]; cleanup: () => void} | undefined;
    if (!prior || dependencies.some((value, i) => value !== prior.dependencies[i])) {
      hooks.effects.push(() => {
        prior?.cleanup();
        hooks.slots[index] = {dependencies, cleanup: effect()};
      });
    }
  },
}));
vi.mock('@/shell/locale-context', () => ({useLocale: () => hooks.locale}));
import View from './view';

type Node = ReactElement<{children?: Node | Node[]; title?: string; busy?: boolean; onClick?: () => void}>;
function nodes(node: Node): Node[] {
  const children = node?.props?.children;
  return [node, ...(Array.isArray(children) ? children : [children]).flatMap(child =>
    child && typeof child === 'object' ? nodes(child) : [])];
}
const pending: ExternalOperation = {
  schema_version: 1, operation_id: 'synthetic_operation_01', actor_id: null, organization_id: null,
  subject_id: null, watch_id: null, expected_revision: 0, state: 'pending', revision: 1,
  pending_reason: 'identity_unavailable', next_actor: 'identity', next_review_at: null,
};
function mount() {
  hooks.slots = []; hooks.effects = []; hooks.locale = 'en';
  return (operation?: ExternalOperation, transport?: Transport) => {
    let tree: Node;
    do {
      hooks.dirty = false; hooks.cursor = 0;
      const child = View({accessPartition: 'current', operation, transport});
      tree = child.type(child.props) as Node;
    } while (hooks.dirty);
    hooks.effects.splice(0).forEach(effect => effect());
    return nodes(tree);
  };
}
describe('mounted private view transitions', () => {
  it('receives loading, completion and denial updates in the same identity', () => {
    const render = mount();
    expect(render().some(node => node.props?.title === 'External sign-in unavailable')).toBe(true);
    expect(render(pending).some(node => node.props?.title === 'Sign-in pending')).toBe(true);
    const completed = {...pending, state: 'signed_in' as const, revision: 2, subject_id: 'buyer'};
    expect(render(completed).some(node => node.props?.title === 'Identity confirmed')).toBe(true);
    hooks.locale = 'ar';
    expect(render(completed).some(node => node.props?.title === 'تم تأكيد الهوية')).toBe(true);
    expect(render({...completed, state: 'denied', revision: 3, subject_id: null})
      .some(node => node.props?.title === 'تعذّر تسجيل الدخول')).toBe(true);
  });
  it('settles the old retry when transport changes and permits the next retry', async () => {
    const render = mount();
    let finish: (value: ExternalOperation) => void = () => {};
    const old: Transport = () => new Promise(resolve => { finish = resolve; });
    const next = vi.fn<Transport>().mockResolvedValue({...pending, state: 'denied', revision: 2});
    render(pending, old).find(node => node.props?.onClick)?.props.onClick?.();
    expect(render(pending, old).some(node => node.props?.busy === true)).toBe(true);
    expect(render(pending, next).some(node => node.props?.busy === true)).toBe(false);
    finish({...pending, state: 'signed_in', revision: 2, subject_id: 'buyer'});
    await new Promise(resolve => setTimeout(resolve, 0));
    render(pending, next).find(node => node.props?.onClick)?.props.onClick?.();
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(next).toHaveBeenCalledTimes(1);
    expect(render(pending, next).some(node => node.props?.title === 'Sign-in unavailable')).toBe(true);
  });
});
