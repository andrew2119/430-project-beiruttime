'use client';
import { useSession } from '@/features/identity/session';
export { authenticatedRequest, signInHref } from '@/features/identity/session';
/** Identity owns restoration, coordinated refresh, memory-only bearer and purge. */
export function useBuyerSession() {
  const session=useSession();
  return {
    signedIn:Boolean(session),
    fingerprint:session?.access_fingerprint??null,
    roles:session?.principal.roles??[],
  };
}
