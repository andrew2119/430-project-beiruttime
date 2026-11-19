import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
import { decodeHistory, decodeRecord } from './model';

export const custodyPath = '/api/web/v1/orders/v1/custody';
export const custodyRead = definePageRead({
  key:(order:string,fingerprint:string)=>['custody.v1',fingerprint,order],
  warm:'open-only',
  ask:async(signal,order:string,fingerprint:string)=>decodeRecord(await authenticatedRequest<unknown>(`${custodyPath}/${encodeURIComponent(order)}`,{signal,accessFingerprint:fingerprint}),order),
});
export const custodyHistoryRead = definePageRead({
  key:(order:string,fingerprint:string,offset:number)=>['custody-history.v1',fingerprint,order,offset],
  warm:'open-only',
  ask:async(signal,order:string,fingerprint:string,offset:number)=>decodeHistory(await authenticatedRequest<unknown>(`${custodyPath}/${encodeURIComponent(order)}/history?offset=${offset}&limit=25`,{signal,accessFingerprint:fingerprint}),order,offset),
});
