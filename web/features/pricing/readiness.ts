export type PaymentDeadline =
  | {state:'notification_pending'}
  | {state:'unavailable'}
  | {state:'known';value:string};

/** Display only the deadline supplied by the order; never derive a new clock. */
export function paymentDeadline(value:unknown):PaymentDeadline {
  if(value===null)return {state:'notification_pending'};
  if(typeof value!=='string'||!Number.isFinite(Date.parse(value)))return {state:'unavailable'};
  return {state:'known',value};
}
