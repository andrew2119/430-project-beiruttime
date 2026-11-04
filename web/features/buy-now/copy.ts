import en from './en.json';
import ar from './ar.json';
import { ApiError } from '@/lib/api/client';
import { normalizeDigits } from '@beirut-time/i18n';
import type {AllocationOperation} from '@contracts/contracts-orders/allocation';
export function copy(locale:'en'|'ar'):Record<string,string>{return locale==='ar'?ar:en;}
export function errorText(error:unknown,t:Record<string,string>){
  if(!(error instanceof ApiError))return t.unavailable;
  if(error.status===401)return t.signInBody;
  if(error.status===403)return t.noPermission;
  if(error.code==='stale_revision')return t.stale;
  return t[error.code]??(error.status===422?t.invalid:t.unavailable);
}
export function requireAcknowledgedOperation(value:AllocationOperation){
  if(value.status==='denied')throw new ApiError(409,value.code??'denied',value.request_id);
  if(value.status!=='succeeded')throw new ApiError(503,value.status,value.request_id);
  return value;
}
export function validatedReservation(value:AllocationOperation,watchId:string,buyerId:string){
  const reference=typeof value.request_id==='string'?value.request_id:'';
  if(!uuid.test(value.id)||!reference)throw new ApiError(503,'invalid_allocation_response',reference);
  if(value.status==='pending'||value.status==='unavailable')throw new ApiError(503,value.status,reference);
  if(value.status==='denied'&&value.payment_authority===false&&!value.order)return value;
  const order=value.order;
  if(value.status!=='succeeded'||!order||order.watch_id!==watchId||order.buyer_id!==buyerId||order.id!==value.resource_id
    ||order.state!=='awaiting_payment'||order.payment_authority!==false||!Number.isSafeInteger(order.total_minor)||order.total_minor<0
    ||!['USD','LBP'].includes(order.currency)||(order.is_demo!==undefined&&typeof order.is_demo!=='boolean')||!Number.isFinite(Date.parse(order.deadline))
    ||!/(Z|[+-]\d{2}:\d{2})$/.test(order.deadline))throw new ApiError(503,'invalid_allocation_response',reference);
  return value;
}
export function canonicalReference(value:string){return normalizeDigits(value).trim().toLowerCase();}
export const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
