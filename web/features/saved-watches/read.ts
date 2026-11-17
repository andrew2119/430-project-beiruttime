import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
import type { SavedList } from '@contracts/contracts-comms/saved-watches';
export const savedBase = '/api/web/v1/communications/v1/saved-watches';
export const savedRead = definePageRead({
  key: (access:string, offset:number) => ['saved-watches.v1', access, offset],
  ask: (signal:AbortSignal, access:string, offset:number) => authenticatedRequest<SavedList>(`${savedBase}?offset=${offset}&limit=20`, {signal, accessFingerprint:access}),
  warm: 'open-only',
  fresh: 0,
});
