import type {Inbox} from '@contracts/contracts-comms/inbox';
import {definePageRead} from '@/lib/page-speed/definition';
import {authenticatedRequest} from './session';

export const inboxRead=definePageRead<[access:string,cursor:string|null,authorizationEpoch?:string],Inbox>({
  key:(access:string,cursor:string|null,authorizationEpoch?:string)=>authorizationEpoch
    ?['inbox',access,'notices',authorizationEpoch,cursor]:['inbox',access,'notices',cursor],
  fresh:0,warm:'open-only',
  ask:(signal,access:string,cursor:string|null)=>authenticatedRequest<Inbox>(
    '/api/web/v1/communications/v1/inbox'+(cursor?'?cursor='+encodeURIComponent(cursor):''),
    {signal,accessFingerprint:access}),
});
