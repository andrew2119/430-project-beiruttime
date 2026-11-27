import type { QueryClient, QueryKey } from '@tanstack/react-query';
import { ApiError } from '../../lib/api/client';
import type { RequestHistory } from '@contracts/contracts-catalog/request-drafts/v2';

export function historyAccessDenied(error: unknown) {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

export async function readPrivateHistory(cache: QueryClient, key: QueryKey, read: () => Promise<RequestHistory>) {
  try {
    return await read();
  } catch (error) {
    if (historyAccessDenied(error)) {
      // Remove private pages before the failed refresh settles for every reader.
      cache.setQueryData(key, { pages: [], pageParams: [] });
    }
    throw error;
  }
}
