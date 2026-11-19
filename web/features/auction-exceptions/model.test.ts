import { describe, expect, it } from 'vitest';
import { boundReceipt, initialDraft, newRequest, prepare, rejected, SubmissionRejected, validReason } from './model';
import { copy } from './copy';
import type { Context, Receipt } from '@contracts/contracts-trust/auction-exceptions/current';
const context: Context = {subject_id:'auction',watch_id:'watch',actor_id:'operator',organization_id:'business',expected_revision:4,quote_id:'quote',quote_revision:2,policy_revision:1,assignment_revision:3};
describe('exception draft', () => {
  it('retains mixed text and exact operation across language and retry', () => {
    const first = prepare({...initialDraft,reason:'سبب خاص mixed 🔒',target:'bidder',action:'retract'},context,'stable-reference');
    for (const locale of ['en','ar'] as const) {
      expect(copy[locale].pending.length).toBeGreaterThan(0);
      expect(prepare(first,context,'another-reference')).toBe(first);
      expect(first.reason).toBe('سبب خاص mixed 🔒');
      expect(first.command?.operation_id).toBe('stable-reference');
      expect(first.command?.target_bidder_id).toBe('bidder');
    }
  });
  it('rejects foreign and malformed receipts', () => {
    const command = prepare(initialDraft,context,'stable-reference').command!;
    const receipt: Receipt = {...command,schema_version:'auction-exceptions.v1',state:'acknowledged',revision:5,code:'competition_recomputed',pending_reason:null,next_actor:null,next_review_at:null};
    expect(boundReceipt(command,receipt)).toBe(true);
    expect(boundReceipt(command,{...receipt,watch_id:'other'})).toBe(false);
    expect(boundReceipt(command,{...receipt,revision:NaN})).toBe(false);
    expect(boundReceipt(command,{...receipt,expected_revision:3})).toBe(false);
    expect(boundReceipt(command,{...receipt,quote_id:'other'})).toBe(false);
    expect(boundReceipt(command,{...receipt,policy_revision:99})).toBe(false);
  });
  it('prepares a fresh reference with current context only after denial', () => {
    const first = prepare({...initialDraft, reason:'Recorded private reason'}, context, 'first');
    expect(newRequest(first)).toBe(first);
    const denied: Receipt = {...first.command!, schema_version:'auction-exceptions.v1', state:'denied', revision:5, code:'stale_revision', pending_reason:null, next_actor:null, next_review_at:null};
    const editable = newRequest({...first, receipt:denied});
    expect(editable.command).toBeNull();
    expect(editable.reason).toBe(first.reason);
    const next = prepare(editable, {...context, expected_revision:5}, 'second');
    expect(next.command?.operation_id).toBe('second');
    expect(next.command?.expected_revision).toBe(5);
    for (const state of ['pending', 'acknowledged'] as const) {
      const retained = {...first, receipt:{...denied, state}};
      expect(newRequest(retained)).toBe(retained);
    }
  });
  it('counts reason characters consistently with the command contract', () => {
    expect(validReason('🔒'.repeat(5))).toBe(false);
    expect(validReason('🔒'.repeat(10))).toBe(true);
    expect(validReason(' \u0085' + '🔒'.repeat(9) + '\u001c')).toBe(false);
    expect(validReason('x'.repeat(2001))).toBe(false);
  });
  it('allows correction only for definitive rejection of the exact operation', () => {
    const first = prepare({...initialDraft, reason:'Recorded private reason'}, context, 'first');
    for (const code of ['invalid_request', 'permission_denied'] as const) {
      const result = rejected(first, new SubmissionRejected('first', code));
      expect(result.command).toBe(first.command);
      expect(result.rejection).toBe(code === 'invalid_request' ? 'error' : 'denied');
      expect(newRequest(result).command).toBeNull();
      expect(newRequest(result).reason).toBe(first.reason);
    }
    for (const error of [new Error('timeout'), new SubmissionRejected('other', 'invalid_request')]) {
      expect(rejected(first, error)).toBe(first);
      expect(newRequest(rejected(first, error))).toBe(first);
    }
  });
  it('accepts lower current revisions only for a bound stale denial', () => {
    const command = prepare(initialDraft, {...context, expected_revision:5}, 'first').command!;
    const receipt: Receipt = {...command, schema_version:'auction-exceptions.v1', state:'denied', revision:4, code:'stale_revision', pending_reason:null, next_actor:null, next_review_at:null};
    expect(boundReceipt(command, receipt)).toBe(true);
    expect(boundReceipt(command, {...receipt, state:'acknowledged'})).toBe(false);
    expect(boundReceipt(command, {...receipt, code:'permission_denied'})).toBe(false);
    expect(boundReceipt(command, {...receipt, revision:-1})).toBe(false);
  });
  it('provides both languages for every recovery message', () => {
    expect(Object.keys(copy.en)).toEqual(Object.keys(copy.ar));
    for (const value of Object.values(copy.ar)) expect(value).toMatch(/[\u0600-\u06ff]/);
  });
});
