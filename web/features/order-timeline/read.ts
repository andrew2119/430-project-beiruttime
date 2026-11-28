import { definePageRead } from '@/lib/page-speed/definition';
import { ApiError } from '@/lib/api/client';
import { authenticatedRequest } from '@/features/identity/session';
import { isOrderPage, isTimeline, type OrderPage, type Timeline } from '@contracts/contracts-comms/order-timeline';

const base = '/api/web/v1/communications/v1/order-timeline';
export const timelineRead = definePageRead({
  key: (id: string | null, organization: string | null, offset: number) => ['l22-order-timeline', id, organization, offset],
  warm: 'open-only', fresh: 0,
  ask: async (signal, id, organization, offset): Promise<Timeline | OrderPage> => {
    const query = new URLSearchParams();
    if (organization) query.set('organization_id', organization);
    if (!id) { query.set('offset', String(offset)); query.set('limit', '20'); }
    const value = await authenticatedRequest<unknown>(`${base}${id ? '/'+encodeURIComponent(id) : ''}?${query}`, {signal});
    if (id ? !isTimeline(value) || value.order_id !== id : !isOrderPage(value) || value.offset !== offset) throw new ApiError(503, 'unavailable', '');
    return value as Timeline | OrderPage;
  },
});
