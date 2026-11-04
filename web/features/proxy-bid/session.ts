'use client';
import { useSession,useSessionState } from '@/features/identity/session';
export { authenticatedRequest,refreshSession,signInHref } from '@/features/identity/session';
/** Identity owns restoration, coordinated refresh, memory-only bearer and purge. */
export function useBuyerSession() {
  const session=useSession(),state=useSessionState();
  return {
    state,
    signedIn:Boolean(session),
    fingerprint:session?.access_fingerprint??null,
    subjectId:session?.principal.actor.subject_id??null,
    roles:session?.principal.roles??[],
  };
}
