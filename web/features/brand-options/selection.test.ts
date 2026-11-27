import { cloneElement, createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Option } from '@contracts/contracts-catalog/options';

const state = vi.hoisted(() => ({
  slots: [] as unknown[], cursor: 0, items: [] as Option[],
  buttons: [] as {disabled?: boolean; onClick: () => void}[],
  radios: [] as {value: string; onChange: () => void}[],
  save: vi.fn(),
}));
vi.mock('react', async importOriginal => {
  const actual = await importOriginal<typeof import('react')>();
  return {...actual, useState: (initial: unknown) => {
    const index = state.cursor++;
    if (!(index in state.slots)) state.slots[index] = initial;
    return [state.slots[index], (value: unknown) => {state.slots[index] = value;}];
  }};
});
vi.mock('@beirut-time/ui', () => ({
  BidiReference: ({children}: {children: React.ReactNode}) => children,
  Card: ({children}: {children: React.ReactNode}) => children,
  Button: (props: {disabled?: boolean; onClick: () => void}) => {state.buttons.push(props); return null;},
  ButtonLink: () => null, Input: () => null, Select: () => null, Label: () => null,
  Segmented: () => null, Skeleton: () => null,
  Radio: (props: {value: string; onChange: () => void}) => {state.radios.push(props); return null;},
  AnimatedList: ({items, children}: {items: Option[]; children: (item: Option) => React.ReactElement}) => items.map(item => cloneElement(children(item), {key: item.id})),
}));
vi.mock('@/shell/page-header', () => ({PageLayout: ({children}: {children: React.ReactNode}) => children, PageHeader: () => null}));
vi.mock('@/shell/locale-context', () => ({useLocale: () => 'en'}));
vi.mock('@/features/identity/session', () => ({
  useSession: () => ({access_fingerprint: 'buyer'}), useSessionState: () => 'authenticated',
}));
vi.mock('@/registry-loader', () => ({hasRoute: () => false}));
vi.mock('./api', () => ({optionsApi: {save: state.save}}));
vi.mock('@/features/movement-option/view', () => ({default: () => null}));
vi.mock('./configuration-review', () => ({default: () => null}));
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({}),
  useInfiniteQuery: () => ({data: {pages: [{items: []}]}}),
  useQuery: ({queryKey}: {queryKey: string[]}) => ({data: queryKey[1] === 'catalog' ? {items: state.items, brand: {name: {en: 'Synthetic brand'}}} : undefined}),
}));
import BrandOptions from './view';

const packageOption: Option = {
  id: 'package', revision: 1, kind: 'sophistication', component: 'package',
  label: {en: 'Synthetic package', ar: 'حزمة تجريبية'}, available: true,
  base_models: ['base'], calibers: ['caliber'],
  details: {interventions: [], exclusions: [], required_tests: [], price_reference: 'Synthetic reference',
    price_minor: 12345, currency: 'USD', conversion: 'none'},
};
function render() {
  state.cursor = 0; state.buttons = []; state.radios = [];
  renderToStaticMarkup(createElement(BrandOptions, {initialBrand: 'brand', initialBase: 'base', initialCaliber: 'caliber'}));
}
describe('active finishing package selection', () => {
  beforeEach(() => {
    state.slots = ['brand', 'base', 'caliber', 'sophistication', ''];
    state.items = [packageOption]; state.save.mockReset();
  });
  it.each([{currency: 'LBP' as const}, {price_minor: -1}, {price_minor: 1.5}, {price_minor: Number.MAX_SAFE_INTEGER + 1}])(
    'excludes an invalid package and rejects a retained selection when saving: %j', change => {
      render();
      expect(state.radios.map(radio => radio.value)).toEqual(['package']);
      state.radios[0].onChange();
      render();
      expect(state.buttons[0].disabled).toBe(false);
      state.items = [{...packageOption, details: {...packageOption.details, ...change}}];
      render();
      expect(state.radios).toEqual([]);
      expect(state.buttons[0].disabled).toBe(true);
      // Invoke the callback directly to verify the command boundary as well as the disabled control.
      state.buttons[0].onClick();
      expect(state.save).not.toHaveBeenCalled();
      expect(state.slots[4]).toBe('package');
    },
  );
  it('rejects a package withdrawn after selection', () => {
    render(); state.radios[0].onChange();
    state.items = [{...packageOption, available: false}];
    render();
    expect(state.buttons[0].disabled).toBe(true);
    state.buttons[0].onClick();
    expect(state.save).not.toHaveBeenCalled();
  });
});
