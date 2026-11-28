import { describe, expect, it } from 'vitest';
import { acceptsResult, beginTransfer } from './model';
import en from './en.json';
import ar from './ar.json';
const bindings = { actor_id: 'seller', organization_id: 'org', subject_id: 'recipient', watch_id: 'watch', sale_id: 'sale', expected_revision: 0, source_revision: 1, quote_revision: 1, policy_revision: 1 };
describe('resale transfer state', () => {
  it('retains exact immutable bindings through language selection and uncertain retry', () => {
    const command = beginTransfer(bindings, 'same-operation');
    for (const language of [en, ar, en]) {
      expect(language.pending).toBeTruthy();
      expect(command.operation_id).toBe('same-operation');
      expect(command).toEqual({ ...bindings, operation_id: 'same-operation' });
      expect(Object.isFrozen(command)).toBe(true);
    }
  });
  it('rejects a response for another operation', () => {
    const command = beginTransfer(bindings, 'same-operation');
    expect(acceptsResult(command, { ...command, schema_version: 'resale-records.v1', operation_id: 'other', state: 'transferred', revision: 1, pending_reason: null, next_actor: 'requester', next_review_at: null })).toBe(false);
  });
  it('rejects wrong scope and revision even with the same operation', () => {
    const command = beginTransfer(bindings, 'same-operation');
    const result = { ...command, schema_version: 'resale-records.v1' as const, state: 'transferred' as const, revision: 1, pending_reason: null, next_actor: 'requester', next_review_at: null };
    expect(acceptsResult(command, result)).toBe(true);
    expect(acceptsResult(command, { ...result, organization_id: 'other' })).toBe(false);
    expect(acceptsResult(command, { ...result, expected_revision: 9 })).toBe(false);
    expect(acceptsResult(command, { ...result, revision: 3 })).toBe(false);
  });
  it('supplies the same recovery states in both languages', () => {
    expect(Object.keys(ar).sort()).toEqual(Object.keys(en).sort());
    for (const value of Object.values(ar)) expect(value.length).toBeGreaterThan(0);
  });
});
