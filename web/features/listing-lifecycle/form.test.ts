import { describe, expect, it, vi } from 'vitest';
import { commandFor, type Fields } from './form';
import { copy } from './copy';
vi.mock('@/features/identity/session', () => ({ authenticatedRequest: vi.fn() }));
import { matches } from './client';
import type { Receipt } from '@contracts/contracts-catalog/listing-lifecycle/v1';
const id = '00000000-0000-4000-8000-000000000001';
const fields: Fields = {listing: id, watch: id, revision: '1', proof: 'proof', quote: 'quote', quoteRevision: '2', policy: 'policy'};
describe('lifecycle form', () => {
  it.each(['0', '-1', '1.5', '1e3', '9007199254740992'])('rejects revision %s', revision => {
    expect(() => commandFor({...fields, revision}, 'renew', id, null, id)).toThrow();
  });
  it('preserves exact commercial and pending references across label selection', () => {
    const pending = commandFor(fields, 'renew', id, null, id);
    for (const locale of ['en', 'ar'] as const) {
      expect(copy[locale].pending).toBeTruthy();
      expect(commandFor(fields, 'renew', id, null, id)).toEqual(pending);
      expect(Object.keys(copy[locale])).toEqual(Object.keys(copy.en));
    }
  });
  it('rejects cross-scope or stale response bindings', () => {
    const command = commandFor(fields, 'relist', id, null, id);
    const receipt = {...command, state: 'pending', revision: 1, pending_reason: 'confirmation_required', next_actor: 'support', next_review_at: '2026-11-18T12:00:00Z', responsible_operator_id: id, next_action: 'resolve_confirmation', escalate_at: '2026-11-19T12:00:00Z', listing_id: null, auction_id: null, previous_auction_id: null} as Receipt;
    expect(matches(command, receipt)).toBe(true);
    expect(matches(command, {...receipt, organization_id: id})).toBe(false);
    expect(matches(command, {...receipt, quote_revision: 3})).toBe(false);
    expect(matches(command, {...receipt, revision: 0})).toBe(false);
  });
});


describe('complete lifecycle receipts', () => {
  const command = commandFor(fields, 'renew', id, null, id);
  const success = {...command, state: 'succeeded', revision: 2, pending_reason: null,
    next_actor: null, next_review_at: null, responsible_operator_id: null, next_action: null, escalate_at: null, listing_id: id, auction_id: null, previous_auction_id: null};
  it('accepts complete fixed-price and linked-auction results', () => {
    expect(matches(command, success)).toBe(true);
    expect(matches(command, {...success, auction_id: id, previous_auction_id: '00000000-0000-4000-8000-000000000002'})).toBe(true);
  });
  it.each([null, {}, {...success, revision: 1}, {...success, auction_id: {private: 'unexpected'}},
    {...success, auction_id: 7}, {...success, listing_id: null}, {...success, listing_id: 'invalid'},
    {...success, previous_auction_id: []}, {...success, next_actor: {}}, {...success, next_review_at: 'invalid'},
    {...success, pending_reason: 'unexpected'}, {...success, extra: 'unexpected'},
    {...success, previous_auction_id: id}, {...success, auction_id: id, previous_auction_id: id},
  ])('rejects malformed results', value => {
    expect(matches(command, value)).toBe(false);
  });
});

it('requires durable pending support ownership and deadlines', () => {
  const command = commandFor(fields, 'renew', id, null, id);
  const pending = {...command, state: 'pending', revision: 1, pending_reason: 'confirmation_required',
    next_actor: 'support', next_action: 'resolve_confirmation', responsible_operator_id: id,
    next_review_at: '2026-11-18T12:00:00Z', escalate_at: '2026-11-19T12:00:00Z',
    listing_id: null, auction_id: null, previous_auction_id: null};
  expect(matches(command, pending)).toBe(true);
  for (const change of [{responsible_operator_id: null}, {next_action: null},
    {next_review_at: null}, {escalate_at: null}, {next_actor: 'seller'},
    {escalate_at: '2026-11-20T12:00:00Z'}, {next_review_at: 'invalid'}]) {
    expect(matches(command, {...pending, ...change})).toBe(false);
  }
});
