'use client';
import {confirmMissingQuote,type ConfirmMissingQuote} from './quote-availability';
import { useSession,useSessionState } from '@/features/identity/session';
export { authenticatedRequest,refreshSession,signInHref } from '@/features/identity/session';
/** Identity owns restoration, coordinated refresh, memory-only bearer and purge. */
export function useBuyerSession() {
  const session=useSession(),state=useSessionState();
  const confirmQuote:ConfirmMissingQuote = (quoteId, access, signal) =>
    state === 'authenticated' && session?.access_fingerprint === access
      ? confirmMissingQuote(quoteId, session.access_token, signal)
      : Promise.resolve(false);
  return {
    confirmMissingQuote:confirmQuote,
    state,
    signedIn:Boolean(session),
    fingerprint:session?.access_fingerprint??null,
    subjectId:session?.principal.actor.subject_id??null,
    organizationId:session?.principal.actor.organization_id??null,
    roles:session?.principal.roles??[],
  };
}
