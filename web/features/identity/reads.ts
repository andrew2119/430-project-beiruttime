'use client';
import type { PrivateApplication } from '@contracts/contracts-identity/accounts';
import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from './session';

export const sellerApplicationRead = definePageRead({
  key:(fingerprint:string)=>['private-seller',fingerprint],
  ask:(signal:AbortSignal,fingerprint:string)=>authenticatedRequest<{application:PrivateApplication|null}>(
    '/api/web/v1/identity/v1/private-seller/applications/me',{signal,accessFingerprint:fingerprint}),
  warm:'open-only'
});
