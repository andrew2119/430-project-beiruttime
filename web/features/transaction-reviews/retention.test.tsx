import { Children, isValidElement, type ReactElement, type ReactNode } from 'react';
import { expect, it, vi } from 'vitest';
import { Input, Select, Textarea } from '@beirut-time/ui/foundation';
const mounted = vi.hoisted(() => ({ slots: [] as unknown[], cursor: 0, locale: 'en' }));
vi.mock('react', async () => ({
  ...await vi.importActual('react'),
  useState: (initial: unknown) => {
    const slot = mounted.cursor++;
    if (!(slot in mounted.slots)) mounted.slots[slot] = initial;
    return [mounted.slots[slot], (next: unknown) => {
      mounted.slots[slot] = typeof next === 'function' ? next(mounted.slots[slot]) : next;
    }];
  },
}));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => mounted.locale }));
vi.mock('@/features/identity/session', () => ({ useSession: () => null, refreshSession: async () => null }));
import { ReviewForm, type Draft } from './screen';
type Node = ReactElement<Record<string, unknown>>;
function elements(value: ReactNode): Node[] {
  if (!isValidElement(value)) return [];
  const node = value as Node;
  return [node, ...Children.toArray(node.props.children as ReactNode).flatMap(elements)];
}
it('retains the same form state and immutable pending reference through both locale transitions', async () => {
  mounted.slots = []; mounted.locale = 'en';
  let finish!: (value: 'pending') => void;
  const transport = vi.fn((_draft: Draft, _reference: string) => { void _draft; void _reference; return new Promise<'pending'>(resolve => { finish = resolve; }); });
  const draw = () => { mounted.cursor = 0; return ReviewForm({ transport }); };
  const field = (id: string) => elements(draw()).find(node => node.props.id === id)!;
  const change = (id: string, value: string) => (field(id).props.onValueChange as (value: string) => void)(value);
  change('review-subject', 'purchase-1');
  change('review-rating', '1');
  change('review-text', 'نقد طويل mixed 🕰️');
  expect(field('review-subject').type).toBe(Input);
  expect(field('review-rating').type).toBe(Select);
  expect(field('review-text').type).toBe(Textarea);
  const send = () => (elements(draw()).find(node => node.type === 'form')!.props.onSubmit as (event: unknown) => void)({ preventDefault() {} });
  send();
  const [draft, reference] = transport.mock.calls[0];
  for (const locale of ['ar', 'en']) {
    mounted.locale = locale;
    expect(field('review-subject').props.value).toBe('purchase-1');
    expect(field('review-rating').props.value).toBe('1');
    expect(field('review-text').props.value).toBe('نقد طويل mixed 🕰️');
    expect(field('review-text').props.disabled).toBe(true);
    expect(elements(draw()).find(node => node.type === 'bdi')!.props.children).toBe(reference);
    expect(transport).toHaveBeenCalledTimes(1);
    expect(field('review-subject').props.label).toBe(locale === 'ar' ? 'مرجع الشراء' : 'Purchase reference');
  }
  finish('pending');
  await Promise.resolve();
  send();
  expect(transport.mock.calls[1]).toEqual([draft, reference]);
  finish('pending');
  await Promise.resolve();
});

it('reports the selected public reference without a purchase reference', async () => {
  const { PublicReviews } = await import('./public');
  const onReport = vi.fn();
  for (const locale of ['en', 'ar']) {
    mounted.locale = locale;
    const tree = PublicReviews({ data: {
      items: [{ review_ref: 'public-review-1', rating: 1, text: 'نقد mixed', reply: null }],
      total: 1, average: 1, distribution: [1, 0, 0, 0, 0], page: 1, next_page: null,
    }, onPage: () => {}, onReport });
    const button = elements(tree).find(node => node.props.children === (locale === 'ar' ? 'الإبلاغ عن المراجعة' : 'Report review'))!;
    (button.props.onClick as () => void)();
    expect(onReport).toHaveBeenLastCalledWith('public-review-1');
  }
});
