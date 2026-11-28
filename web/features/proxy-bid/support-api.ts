import {ApiError} from '@/lib/api/client';
import {definePageRead} from '@/lib/page-speed/definition';
import {authenticatedRequest} from './session';

export type SupportMessage={sequence:number;author:'buyer'|'support';body:string;sent_at:string};
export type SupportConversation={schema_version:1;auction_id:string;buyer_id:string;conversation_id:string;
  order_id:string|null;revision:number;hold_state:'active'|'resolved';assignment_state:'awaiting_operator'|'assigned';operator_id:string|null;
  follow_up_due_at:string;escalate_at:string;items:SupportMessage[];next_cursor:string|null};
export type SupportCommand=Readonly<{conversation_id:string;expected_revision:number;body:string}>;
type AttemptState='prepared'|'accepted'|'stale'|'abandoned';
export type SupportReceipt={schema_version:1;operation_id:string;conversation_id:string;auction_id:string;buyer_id:string;
  state:AttemptState;revision:number};

const uuid=(value:unknown):value is string=>typeof value==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value);
const revision=(value:unknown):value is number=>typeof value==='number'&&Number.isSafeInteger(value)&&value>0;
const clock=(value:unknown)=>typeof value==='string'&&/T.*(?:Z|\+00:00)$/.test(value)&&Number.isFinite(Date.parse(value));
const path=(auction:string)=>`/api/web/v1/communications/v1/support/auction-results/${encodeURIComponent(auction)}`;
const failed=()=>new ApiError(503,'invalid_support_response','');
export function supportBody(body:string) {return Boolean(body.trim())&&Array.from(body).length<=2000;}

function verified(value:SupportConversation,auction:string,buyer:string,cursor?:string|null) {
  if(value?.schema_version!==1||value.auction_id!==auction||value.buyer_id!==buyer||!uuid(value.conversation_id)||
    (value.order_id!==null&&!uuid(value.order_id))||!revision(value.revision)||
    !['active','resolved'].includes(value.hold_state)||
    (value.assignment_state==='assigned'?!uuid(value.operator_id):value.assignment_state!=='awaiting_operator'||value.operator_id!==null)||
    !clock(value.follow_up_due_at)||!clock(value.escalate_at)||Date.parse(value.escalate_at)-Date.parse(value.follow_up_due_at)!==86_400_000||
    !Array.isArray(value.items)||value.items.length>30||value.items.some((row,index)=>!row||!revision(row.sequence)||
      (index>0&&row.sequence<=value.items[index-1].sequence)||!['buyer','support'].includes(row.author)||
      typeof row.body!=='string'||!supportBody(row.body)||!clock(row.sent_at))||
    (value.next_cursor!==null&&(typeof value.next_cursor!=='string'||!value.next_cursor.length||value.next_cursor.length>200||
      !value.items.length||value.next_cursor===cursor))) throw failed();
  return value;
}

export const supportRead=definePageRead({
  key:(auction:string,buyer:string,access:string,cursor:string|null,accessEpoch=0)=>['auction-support',access,buyer,auction,accessEpoch,cursor],
  fresh:0,warm:'open-only',
  ask:async(signal,auction:string,buyer:string,access:string,cursor:string|null,_accessEpoch?:number)=>{
    const url=path(auction)+(cursor?`?cursor=${encodeURIComponent(cursor)}`:'');
    const value=await authenticatedRequest<SupportConversation>(url,{signal,accessFingerprint:access,cache:'no-store'});
    return verified(value,auction,buyer,cursor);
  },
});

export async function openSupport(auction:string,buyer:string,access:string,key:string,signal:AbortSignal) {
  const value=await authenticatedRequest<SupportConversation>(path(auction),{signal,accessFingerprint:access,cache:'no-store',
    method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:'{}'});
  return verified(value,auction,buyer);
}

async function attempt(auction:string,buyer:string,access:string,key:string,phase:'prepare'|'deliver'|'check',
  command:SupportCommand|{conversation_id:string},signal:AbortSignal) {
  if(!uuid(key)||!uuid(command.conversation_id)) throw failed();
  const value=await authenticatedRequest<SupportReceipt>(`${path(auction)}/message-attempts/${key}/${phase}`,{
    signal,accessFingerprint:access,cache:'no-store',method:'POST',
    headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(command)});
  if(value?.schema_version!==1||Object.keys(value).length!==7||value.operation_id!==key||value.conversation_id!==command.conversation_id||
    value.auction_id!==auction||value.buyer_id!==buyer||!revision(value.revision)||
    !['prepared','accepted','stale','abandoned'].includes(value.state)||(phase==='deliver'&&value.state==='prepared')||
    (value.state==='accepted'&&'expected_revision' in command&&value.revision<=command.expected_revision)) throw failed();
  return value;
}

export const prepareSupport=(auction:string,buyer:string,access:string,key:string,command:SupportCommand,signal:AbortSignal)=>
  attempt(auction,buyer,access,key,'prepare',command,signal);
export const deliverSupport=(auction:string,buyer:string,access:string,key:string,conversationId:string,signal:AbortSignal)=>
  attempt(auction,buyer,access,key,'deliver',{conversation_id:conversationId},signal);
export const checkSupport=(auction:string,buyer:string,access:string,key:string,conversationId:string,signal:AbortSignal)=>
  attempt(auction,buyer,access,key,'check',{conversation_id:conversationId},signal);
