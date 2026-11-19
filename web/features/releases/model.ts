import { conditions, type Command, type Condition, type Operation, type Preview } from '@contracts/contracts-orders/releases';
export const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const minor = (v:unknown):v is number=>typeof v === 'number' && Number.isSafeInteger(v) && v >= 0;
const revision = (v:unknown)=>minor(v) && v > 0;
const instant = (v:unknown):v is string=>typeof v === 'string' && /(?:Z|\+00:00)$/.test(v) && Number.isFinite(Date.parse(v));
const record = (v:unknown):Record<string,unknown>=>{if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error('invalid_release');return v as Record<string,unknown>;};
const missing = (v:unknown):v is Condition[]=>Array.isArray(v) && v.length <= conditions.length && v.every(x=>conditions.includes(x));
function bindings(value:Record<string,unknown>) {
  return ['subject_id','watch_id','quote_id','recipient_id'].every(k=>typeof value[k] === 'string' && uuid.test(value[k] as string))
    && (value.organization_id === null || typeof value.organization_id === 'string' && uuid.test(value.organization_id))
    && ['quote_revision','policy_revision','recipient_revision'].every(k=>revision(value[k]));
}
export function preview(value:unknown,order:string,organization:string|null):Preview {
  const v = record(value), s = record(v.snapshot);
  if (!bindings(s) || s.subject_id !== order || s.organization_id !== organization || !revision(s.revision) || s.currency !== 'USD'
    || !['principal_minor','buyer_fee_minor','business_fee_minor','total_minor'].every(k=>minor(s[k]))
    || Number(s.total_minor) !== Number(s.principal_minor)+Number(s.buyer_fee_minor)
    || Number(s.business_fee_minor) > Number(s.principal_minor) || v.simulated !== true || !missing(v.missing)
    || !(s.active_release_operation_id === null || typeof s.active_release_operation_id === 'string' && uuid.test(s.active_release_operation_id))
    || !(v.closes_at === null || instant(v.closes_at))) throw new Error('invalid_release');
  return value as Preview;
}
export function operation(value:unknown,command:Command):Operation {
  const v = record(value);
  if (Object.entries(command).some(([k,x])=>v[k] !== x) || !revision(v.revision) || !missing(v.missing)
    || !['denied','pending','paid_out','unavailable'].includes(String(v.state)) || v.simulated !== true
    || !(v.responsible_operator_id === null || typeof v.responsible_operator_id === 'string' && uuid.test(v.responsible_operator_id))
    || !(v.responsibility_revision === null || revision(v.responsibility_revision))
    || !['review_conditions','reconcile_transfer','complete'].includes(String(v.next_action))
    || (!['response_unknown','dependency_unavailable'].includes(String(v.pending_reason))
      && (v.responsible_operator_id === null || v.responsibility_revision === null))
    || !['operator','payout_operator'].includes(String(v.next_actor)) || !instant(v.next_review_at)
    || ![null,'transfer_pending','transfer_failed','response_unknown','dependency_unavailable'].includes(v.pending_reason as null)
    || ![v.gross_minor,v.fee_minor,v.net_minor].every(x=>x === null || minor(x))) throw new Error('invalid_release');
  const money = [v.gross_minor,v.fee_minor,v.net_minor];
  if (money.some(x=>x !== null) && (money.some(x=>x === null) || v.gross_minor !== Number(v.fee_minor)+Number(v.net_minor))) throw new Error('invalid_release');
  if (v.state === 'paid_out' && (v.net_minor === null || v.missing.length > 0 || v.pending_reason !== null)) throw new Error('invalid_release');
  return value as Operation;
}
export type Memory = {command:Command; result:Operation|null};
export function pending(memory:Memory) {return !memory.result || memory.result.state === 'pending' || memory.result.state === 'unavailable';}
export function dollars(minorUnits:number):string {
  if (!minor(minorUnits)) throw new Error('invalid_amount');
  const whole = Math.floor(minorUnits/100), cents = minorUnits%100;
  return String(whole)+'.'+String(cents).padStart(2,'0');
}

export function commandOf(value:Operation):Command {
  const {schema_version,operation_id,subject_id,watch_id,actor_id,organization_id,expected_revision,
    quote_id,quote_revision,policy_revision,recipient_id,recipient_revision} = value;
  return {schema_version,operation_id,subject_id,watch_id,actor_id,organization_id,expected_revision,
    quote_id,quote_revision,policy_revision,recipient_id,recipient_revision};
}
export function restoredOperation(value:unknown,id:string,actor:string,organization:string|null,subject:string):Operation {
  const v = record(value);
  if (!bindings(v) || v.schema_version !== 'orders.releases.v1' || v.operation_id !== id || !uuid.test(id)
    || v.actor_id !== actor || !uuid.test(actor) || v.organization_id !== organization
    || v.subject_id !== subject || !revision(v.expected_revision)) throw new Error('invalid_release');
  return operation(value,commandOf(value as Operation));
}
