import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { LocaleContext } from '../../../../web/shell/locale-context';
import { FactsView, ComparisonColumn } from '../../../../web/features/comparison/view';
import { messages } from '../../../../web/features/comparison/messages';
import { addSelection, minorDecimal, compareBody } from '../../../../web/features/comparison/state';
import { decodeComparison } from '../../../../web/features/comparison/validate';
import fixtures from '../../../../packages/contracts-catalog/comparison/fixtures.json';
import type { Comparison, CompareRequest, Column } from '../../../../packages/contracts-catalog/comparison';

const request = fixtures.request as CompareRequest;
const success = fixtures.success as Comparison;
const noop = () => {};
describe('comparison public view', () => {
  it('accepts only the exact bound response', () => {
    expect(decodeComparison(success, success.operation_id, request)).toEqual(success);
    expect(() => decodeComparison(success, 'another', request)).toThrow();
    expect(() => decodeComparison({ ...success, evidence_refs: ['private'] }, success.operation_id, request)).toThrow();
    const changed = structuredClone(success); changed.columns[0].watch_id = 'another';
    expect(() => decodeComparison(changed, success.operation_id, request)).toThrow();
  });
  it('rejects stale facts and private identity even if a source sends them', () => {
    const changed = structuredClone(success); changed.columns[0].state = 'stale';
    expect(() => decodeComparison(changed, success.operation_id, request)).toThrow();
    const privateFacts = { ...success.columns[0].facts, seller_identity: 'restricted' };
    expect(() => decodeComparison({ ...success, columns: [{ ...success.columns[0], facts: privateFacts }] }, success.operation_id, request)).toThrow();
  });
  it('bounds and deduplicates selection without losing the current choice', () => {
    const one = addSelection([], 'first')!;
    expect(addSelection(one, 'first')).toBeNull();
    expect(addSelection(one, '../private')).toBeNull();
    const three = addSelection(addSelection(one, 'second')!, 'third')!;
    expect(addSelection(three, 'fourth')).toBeNull();
    expect(compareBody(three).selections).toBe(three);
    expect(minorDecimal(515000)).toBe('5150.00');
    expect(minorDecimal(1)).toBe('0.01');
    expect(() => minorDecimal(Infinity)).toThrow();
  });
  for (const locale of ['en','ar'] as const) {
    it(`renders exact facts, missing documents and fees in ${locale}`, () => {
      const html = renderToStaticMarkup(<LocaleContext.Provider value={locale}><FactsView facts={success.columns[0].facts!}/></LocaleContext.Provider>);
      expect(html).toContain(messages[locale].noDocuments);
      expect(html).toContain(messages[locale].not_inspected);
      expect(html).toContain(messages[locale].economics);
      expect(html).not.toContain('seller_id');
    });
    for (const state of ['denied','unavailable','pending','stale'] as const) {
      it(`retains ${state} column and recovery in ${locale}`, () => {
        const column = fixtures[state].columns[0] as Column;
        const html = renderToStaticMarkup(<LocaleContext.Provider value={locale}><ComparisonColumn column={column} busy={false} onRemove={noop} onRetry={noop} onReview={noop}/></LocaleContext.Provider>);
        expect(html).toContain(messages[locale][state]);
        expect(html).toContain('demo-13');
        expect(html).not.toContain('Synthetic watch');
        expect(html).not.toContain('5150');
      });
    }
  }
  it('hides retained facts during a refresh', () => {
    const html = renderToStaticMarkup(<ComparisonColumn column={success.columns[0]} busy onRemove={noop} onRetry={noop} onReview={noop}/>);
    expect(html).not.toContain('Synthetic watch');
    expect(html).toContain(messages.en.refresh);
  });
  it('wraps mixed content without changing identifiers or exact amounts', () => {
    const facts = structuredClone(success.columns[0].facts!);
    facts.title = { en: '⌚ Arabic العربية Latin '.repeat(70), ar: 'العربية Latin ⌚ '.repeat(70) };
    facts.reference = 'EXACT-13'; facts.year = null; facts.price_minor = null; facts.buyer_fee_minor = null; facts.total_minor = null;
    const html = renderToStaticMarkup(<FactsView facts={facts}/>);
    expect(html).toContain('EXACT-13');
    expect(html).toContain(messages.en.missing);
  });
});
