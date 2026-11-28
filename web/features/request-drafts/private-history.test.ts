import { InfiniteQueryObserver, QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { ApiError } from '../../lib/api/client';
import fixture from '../../../packages/contracts-catalog/request-drafts/fixtures/request.v2.json';
import type { RequestHistory } from '@contracts/contracts-catalog/request-drafts/v2';
import { historyAccessDenied, readPrivateHistory } from './private-history';

describe('private history refresh', () => {
  it.each([401, 403, 503])('handles success followed by HTTP %s', async status => {
    const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    const key = ['customization-history', 'current-buyer', 'request', 1];
    const page: RequestHistory = { items: [{ ...fixture.request, actor_id: fixture.request.buyer_id, reason: 'Private correction نص ⌚' } as RequestHistory['items'][number]], current_revision: 1, total: 1, next_cursor: null };
    let failure: ApiError | null = null;
    const observer = new InfiniteQueryObserver(cache, {
      queryKey: key,
      initialPageParam: null,
      getNextPageParam: () => undefined,
      queryFn: () => readPrivateHistory(cache, key, async () => {
        if (failure) throw failure;
        return page;
      }),
    });
    const unsubscribe = observer.subscribe(() => {});
    try {
      await observer.refetch();
      expect(observer.getCurrentResult().data?.pages).toEqual([page]);
      failure = new ApiError(status, 'unavailable', 'same-read');
      await observer.refetch();
      const result = observer.getCurrentResult();
      expect(result.error).toBe(failure);
      expect(historyAccessDenied(result.error)).toBe(status !== 503);
      const expected = status === 503 ? [page] : [];
      expect(result.data?.pages).toEqual(expected);
      expect(cache.getQueryData<{ pages: RequestHistory[] }>(key)?.pages).toEqual(expected);
      failure = null;
      await observer.refetch();
      expect(observer.getCurrentResult().data?.pages).toEqual([page]);
    } finally {
      unsubscribe();
      cache.clear();
    }
  });
});
