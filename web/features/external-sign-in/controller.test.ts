import { describe, expect, it, vi } from 'vitest';
import type { ExternalOperation } from '@contracts/contracts-identity/external-sign-in';
import { OperationController } from './controller';
const operation: ExternalOperation = {
  schema_version: 1, operation_id: 'synthetic_operation_01', actor_id: 'buyer', organization_id: 'business',
  subject_id: null, watch_id: null, expected_revision: 3, state: 'pending', revision: 1,
  pending_reason: 'identity_unavailable', next_actor: 'identity', next_review_at: null,
};
describe('private external operation', () => {
  it('retains the exact operation on uncertain retry', async () => {
    const transport = vi.fn().mockRejectedValue(new Error('unavailable'));
    const owner = new OperationController(transport);
    expect(await owner.retry(operation)).toEqual(operation);
    expect(transport.mock.calls[0][0]).toEqual(operation);
  });
  it.each([
    {operation_id: 'another_operation'}, {actor_id: 'other'}, {organization_id: 'other'},
    {expected_revision: 4}, {revision: 0}, {revision: NaN}, {revision: 1.5},
    {schema_version: 2}, {state: 'invented'}, {state: 'linked', subject_id: 'other'},
  ])('rejects changed bindings %j', async change => {
    const owner = new OperationController(async () => ({...operation, ...change}) as ExternalOperation);
    expect(await owner.retry(operation)).toEqual(operation);
  });
  it('clears a late answer after access changes', async () => {
    let finish: (value: ExternalOperation) => void = () => {};
    const owner = new OperationController(() => new Promise(resolve => { finish = resolve; }));
    const result = owner.retry(operation);
    owner.clear();
    finish({...operation, state: 'linked', subject_id: 'buyer', revision: 2});
    expect(await result).toBeNull();
  });
  it('bounds a hung request and retains its reference', async () => {
    vi.useFakeTimers();
    const owner = new OperationController(() => new Promise(() => {}));
    const result = owner.retry(operation);
    await vi.advanceTimersByTimeAsync(2000);
    expect(await result).toEqual(operation);
    vi.useRealTimers();
  });
  it('accepts the current receipt without changing its binding', async () => {
    const answer = {...operation, state: 'linked' as const, subject_id: 'buyer', revision: 2, pending_reason: null};
    const owner = new OperationController(async () => answer);
    expect(await owner.retry(operation)).toEqual(answer);
  });
});
