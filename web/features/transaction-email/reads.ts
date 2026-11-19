import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
import type { EmailPage, EmailRecord } from '@contracts/contracts-comms/transaction-email';
export const base = '/api/web/v1/communications/v1/transaction-email';
export const emailRead = definePageRead({
  key: (scope:string, offset:number)=>['transaction-email.v1', scope, offset],
  ask: (signal:AbortSignal, scope:string, offset:number)=>authenticatedRequest<EmailPage>(`${base}?offset=${offset}&limit=20`, {signal, accessFingerprint:scope}),
  warm: 'open-only', fresh: 0,
});
export const operationRead = definePageRead({
  key: (scope:string, operation:string)=>['transaction-email.v1', scope, 'operation', operation],
  ask: (signal:AbortSignal, scope:string, operation:string)=>authenticatedRequest<EmailRecord>(`${base}/operations/${operation}`, {signal, accessFingerprint:scope}),
  warm: 'open-only', fresh: 0,
});
export function operationReference(value:string|null) {return value !== null && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value) ? value : null;}
export function safeDestination(value:string) {return /^\/(?:checkout|prices)\/[0-9a-f-]{36}$/.test(value) || value === '/inbox';}
