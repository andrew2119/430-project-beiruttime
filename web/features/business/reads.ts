'use client';
import { definePageRead, type PageRead } from '@/lib/page-speed/definition';
import { usePageRead } from '@/lib/page-speed/read';
import { businessRequest } from './transport';
import { pagedRequest } from './pagination';
import type { Contacts, OfficialBusiness, PrivateReview } from '@contracts/contracts-identity/businesses';

/** The same definitions serve intent and mounted reads under the root access scope. */
export const directoryRead = definePageRead({
  key: (page: number) => ['business-v2', 'businesses', page],
  warm: 'safe',
  ask: (signal, page: number) => pagedRequest<OfficialBusiness>('/v2/businesses', page, false, signal),
});
export const contactsRead = definePageRead({
  key: (access: string | null) => ['l02', 'contacts', access],
  warm: 'open-only',
  ask: (signal, access: string | null) => {
    void access;
    return businessRequest<Contacts>('/v1/contacts', { signal });
  },
});
export const reviewQueueRead = definePageRead({
  key: (access: string | null, page: number) => ['business-v2', 'reviews', access, page],
  warm: 'open-only',
  ask: (signal, _access: string | null, page: number) => pagedRequest<PrivateReview>('/v2/private-reviews', page, true, signal),
});
export const ownReviewsRead = definePageRead({
  key: (access: string | null, page: number) => ['business-v2', 'my-reviews', access, page],
  warm: 'open-only',
  ask: (signal, _access: string | null, page: number) => pagedRequest<PrivateReview>('/v2/private-reviews/mine', page, true, signal),
});

/** Parameterized private workspaces are opened explicitly, never read on hover. */
export function businessRead<T>(queryKey: readonly unknown[], queryFn: () => Promise<T>) {
  return definePageRead({key: () => queryKey, ask: async signal => {
    signal.throwIfAborted();
    const answer = await queryFn();
    signal.throwIfAborted();
    return answer;
  }, warm: 'open-only'})();
}
export function useBusinessRead<T>({queryKey,queryFn,enabled=true,read}: {
  queryKey: readonly unknown[]; queryFn: () => Promise<T>; enabled?: boolean; retry?: boolean; read?: PageRead<T>;
}) {
  return usePageRead(enabled ? read ?? businessRead(queryKey, queryFn) : null);
}

export const businessRouteReads = {
  '/business': () => directoryRead(1),
  '/business/contacts': contactsRead,
  '/business/review-history': (access: string | null) => ownReviewsRead(access, 1),
  '/business/membership': () => null,
  '/operations/verification': (access: string | null) => reviewQueueRead(access, 1),
} as const;
