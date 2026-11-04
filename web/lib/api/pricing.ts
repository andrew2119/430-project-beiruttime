import { request } from './client';
import type { ServiceStatus } from './types';
// Domain-owned API module. Extend with versioned, typed commands and reads.
export const pricingApi = {
  status: (signal?: AbortSignal) => request<ServiceStatus>('/api/web/v1/status/pricing', { signal }),
};
