import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../lib/api/client';
import { purge } from './memory';
import { readPrivateDrafts } from './private-drafts';

describe('private read access boundary', () => {
  it.each([401, 403, 503])('preserves the failure and revokes only denied access for HTTP %s', async status => {
    const revoke = vi.fn(), error = new ApiError(status, 'unavailable', 'current-read');
    await expect(readPrivateDrafts(async () => { throw error; }, revoke)).rejects.toBe(error);
    expect(revoke).toHaveBeenCalledTimes(status === 503 ? 0 : 1);
  });

  it('does not revoke a new workspace for a late denial from the previous access generation', async () => {
    let reject!: (error: unknown) => void;
    const answer = new Promise<never>((_resolve, failure) => { reject = failure; });
    const revoke = vi.fn(), pending = readPrivateDrafts(() => answer, revoke);
    purge();
    const error = new ApiError(403, 'forbidden', 'old-read');
    reject(error);
    await expect(pending).rejects.toBe(error);
    expect(revoke).not.toHaveBeenCalled();
  });
});
