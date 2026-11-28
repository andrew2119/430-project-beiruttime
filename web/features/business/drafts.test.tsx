import { afterEach, expect, it, vi } from 'vitest';

const mounted = vi.hoisted(() => ({ slots: [] as unknown[], index: 0, effects: [] as (() => void)[] }));
vi.mock('react', async original => ({
  ...await original<typeof import('react')>(),
  useCallback: (callback: unknown) => callback,
  useState: (initial: unknown) => {
    const index = mounted.index++;
    if (!(index in mounted.slots)) mounted.slots[index] = initial;
    return [mounted.slots[index], (value: unknown) => { mounted.slots[index] = value; }];
  },
  useRef: (initial: unknown) => {
    const index = mounted.index++;
    if (!(index in mounted.slots)) mounted.slots[index] = { current: initial };
    return mounted.slots[index];
  },
  useEffect: (effect: () => void) => { mounted.effects.push(effect); },
}));
vi.mock('@/shell/private-state', () => ({
  readNonSecretDraft: () => JSON.stringify({ capabilities: ['servicing'], sample: true }),
  saveNonSecretDraft: vi.fn(),
}));
import { Checkbox } from './checkbox';
import { usePublicBusinessDraft } from './drafts';

class Input extends EventTarget {
  checked = false;
  defaultChecked = false;
  constructor(public name: string, public value: string, public form: EventTarget) { super(); }
}
afterEach(() => { vi.unstubAllGlobals(); });

it('keeps restored choices through English and Arabic renders and submission', () => {
  mounted.slots = []; mounted.index = 0; mounted.effects = [];
  vi.stubGlobal('HTMLInputElement', Input);
  vi.stubGlobal('HTMLSelectElement', class {});
  const form = new EventTarget();
  const inputs = [new Input('capabilities', 'sales', form), new Input('capabilities', 'servicing', form), new Input('sample', 'on', form)];
  const render = (locale: 'en' | 'ar') => {
    mounted.index = 0;
    return inputs.map(input => {
      const element = Checkbox({ name: input.name, value: input.value, defaultChecked: input.value === 'sales', children: locale === 'en' ? 'Choice' : 'خيار' });
      input.checked = element.props.children.props.checked;
      element.props.ref.current = { querySelector: () => input };
      return element;
    });
  };
  render('en');
  // Child effects subscribe before the parent's restoration effect runs.
  mounted.effects.splice(0).forEach(effect => effect());
  const draft = usePublicBusinessDraft('test-owner');
  draft.attachForm({
    elements: { namedItem: (name: string) => inputs.find(input => input.name === name) },
    querySelectorAll: () => inputs.filter(input => input.name === 'capabilities'),
  } as unknown as HTMLFormElement);
  mounted.effects.splice(0).forEach(effect => effect());
  for (const locale of ['ar', 'en', 'ar'] as const) {
    render(locale);
    const submission = new FormData();
    inputs.filter(input => input.checked).forEach(input => submission.append(input.name, input.value));
    expect(submission.getAll('capabilities')).toEqual(['servicing']);
    expect(submission.get('sample')).toBe('on');
  }
});
