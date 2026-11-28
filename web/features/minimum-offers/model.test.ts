import { describe, expect, it } from 'vitest';
import { dollarCents, dollars, settle, formReducer, localizedForm, type FormDraft, type Operation } from './model';
import { copy } from './copy';
const operation: Operation = { phase: 'pending', command: {
  schema_version: 1, operation_id: 'one', actor_id: 'seller', organization_id: 'business',
  subject_id: 'listing', watch_id: 'watch', expected_revision: 0, source_revision: 2,
  policy_revision: 3, quote_id: 'quote', quote_revision: 4, minimum_minor: 10000,
} };
const envelope = {subject_id: 'listing', watch_id: 'watch', actor_id: 'seller', organization_id: 'business', expected_revision: 0, revision: null, pending_reason: null, next_actor: null, next_review_at: null};
describe('private minimum form', () => {
  it('keeps exact dollars in either digit script', () => {
    expect(dollarCents('100.01')).toBe(10001);
    expect(dollarCents('١٠٠٫٠١')).toBe(10001);
    expect(dollars(10001)).toBe('100.01');
    for (const value of ['0', '-1', '1e3', '1.001', 'Infinity', '90071992547409.92']) expect(dollarCents(value)).toBeNull();
  });
  it('keeps pending identity for unavailable and mismatched responses', () => {
    expect(settle(operation, { ...envelope, schema_version: 1, operation_id: 'other', state: 'saved' })).toBe(operation);
    expect(settle(operation, { ...envelope, schema_version: 1, operation_id: 'one', state: 'unavailable' }).command).toBe(operation.command);
    expect(settle(operation, { ...envelope, schema_version: 1, operation_id: 'one', state: 'saved', revision: 9, minimum_minor: 10000 })).toBe(operation);
    expect(settle(operation, { ...envelope, schema_version: 1, operation_id: 'one', state: 'saved', revision: 1, minimum_minor: 10000 }).phase).toBe('saved');
  });
  it('retains the pending command when any private envelope binding differs', () => {
    const result = { ...envelope, schema_version: 1 as const, operation_id: 'one', state: 'saved' as const, revision: 1, minimum_minor: 10000 };
    const mismatches = { actor_id: 'other-seller', organization_id: 'other-business', subject_id: 'other-listing', watch_id: 'other-watch', expected_revision: 9 };
    for (const state of ['saved', 'stale', 'pending', 'unavailable'] as const) {
      for (const key of Object.keys(mismatches) as (keyof typeof mismatches)[]) {
        expect(settle(operation, { ...result, state, [key]: mismatches[key] })).toBe(operation);
      }
      expect(settle(operation, { ...result, state, ...mismatches })).toBe(operation);
    }
    expect(settle(operation, result).phase).toBe('saved');
    expect(settle(operation, { schema_version: 1, operation_id: 'one', state: 'denied' }).phase).toBe('denied');
  });
  it('has complete matching language states without changing an operation', () => {
    expect(Object.keys(copy.en).sort()).toEqual(Object.keys(copy.ar).sort());
    let draft: FormDraft = {amount: null, operation: null};
    draft = formReducer(draft, {type: 'amount', value: '١٠٠٫٠١'});
    draft = formReducer(draft, {type: 'operation', value: operation});
    for (const locale of ['ar', 'en', 'ar'] as const) {
      const shown = localizedForm(draft, locale);
      expect(shown.text).toBe(copy[locale]);
      expect(shown.draft).toBe(draft);
      expect(shown.draft.amount).toBe('١٠٠٫٠١');
      expect(shown.draft.operation?.command).toBe(operation.command);
      expect(shown.draft.operation?.phase).toBe('pending');
    }
    draft = formReducer(draft, {type: 'operation', value: settle(operation, {...envelope, schema_version: 1, operation_id: 'one', state: 'saved', revision: 1, minimum_minor: 10000})});
    expect(localizedForm(draft, 'ar').draft.operation?.phase).toBe('saved');
  });
});
