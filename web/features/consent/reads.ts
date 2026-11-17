import type { PrivateConsent } from '@contracts/contracts-eligibility/consent';
import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '../identity/session';
export const consentRead = definePageRead({
  key: (fingerprint:string,page:number) => ['consent',fingerprint,page],
  warm: 'open-only', fresh: 0,
  ask: (signal:AbortSignal,fingerprint:string,page:number) => authenticatedRequest<{consents:PrivateConsent[];total:number;page:number}>(`/api/web/v1/eligibility/v1/consents?page=${page}`,{signal,accessFingerprint:fingerprint}),
});
