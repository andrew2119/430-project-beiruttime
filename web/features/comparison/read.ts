import type { Comparison, CompareRequest } from '@contracts/contracts-catalog/comparison';
import { request } from '@/lib/api/client';
import { definePageRead } from '@/lib/page-speed/definition';
import { decodeComparison } from './validate';
export const comparisonRead = definePageRead({
  key: (operation: string, body: CompareRequest) => ['comparison.v1', operation, JSON.stringify(body)],
  ask: async (signal: AbortSignal, operation: string, body: CompareRequest): Promise<Comparison> => {
    const result = await request<unknown>(`/api/web/v1/catalog/v1/comparison/operations/${encodeURIComponent(operation)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
    });
    return decodeComparison(result, operation, body);
  },
  warm: 'open-only', fresh: 0,
});
