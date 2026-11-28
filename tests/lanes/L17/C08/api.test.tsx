import { describe, expect, it, vi } from 'vitest';
const request = vi.hoisted(() => vi.fn());
vi.mock('@/features/identity/session', () => ({ authenticatedRequest: request }));
import { lookupOperation } from '../../../../web/features/brand-assessment/api';

describe('Pending operation recovery', () => {
  it('reads the exact retained reference without submitting a command', async () => {
    const retained = { operation_id: 'same/reference', state: 'correction_pending' };
    request.mockResolvedValue(retained);
    expect(await lookupOperation('request/one', retained.operation_id)).toBe(retained);
    expect(request).toHaveBeenCalledExactlyOnceWith(
      '/api/web/v1/service-operations/v1/brand-assessments/request%2Fone/operations/same%2Freference');
  });
});
