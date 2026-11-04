import { request } from './client';
import type { ServiceStatus } from './types';
// Domain-owned API module. Extend with versioned, typed commands and reads.
export const trustApi = {
  status: (signal?: AbortSignal) => request<ServiceStatus>('/api/web/v1/status/trust', { signal }),
};
