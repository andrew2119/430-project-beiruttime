import { custodyStates, custodyVersion, type CustodyRecord, type ReceiptProof, type BuyerReceiptCommand, type CustodyHistory } from '@contracts/contracts-orders/custody';

export const reference = (value:string) => /^[A-Za-z0-9_-]{1,100}$/.test(value);
export class ReceiptAttempt {
  private pending:Readonly<{operation:string;order:string;revision:number;body:string}>|null = null;
  capture(command?:BuyerReceiptCommand) {
    if (!this.pending && command) this.pending = Object.freeze({operation:command.operation_id,order:command.subject_id,revision:command.expected_revision,body:JSON.stringify(command)});
    return this.pending;
  }
  unresolved() {return this.pending !== null;}
  clear() {this.pending=null;}
}
const integer = (value:unknown) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const object = (value:unknown):value is Record<string,unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const utc = (value:unknown) => typeof value === 'string' && /(?:Z|\+00:00)$/.test(value) && Number.isFinite(Date.parse(value));

export function decodeRecord(value:unknown, order:string):CustodyRecord|null {
  if (!object(value) || value.schema_version !== custodyVersion || !('result' in value)) throw new Error('invalid');
  if (value.result === null) return null;
  const row = value.result;
  if (!object(row) || row.schema_version !== custodyVersion || row.subject_id !== order || !integer(row.revision) || !object(row.current)) throw new Error('invalid');
  const current = row.current;
  for (const field of ['watch_id','quote_id','actor_id']) if (typeof current[field] !== 'string' || !reference(current[field])) throw new Error('invalid');
  for (const field of ['watch_revision','source_revision','quote_revision','policy_revision']) if (!integer(current[field])) throw new Error('invalid');
  if (current.organization_id !== null && (typeof current.organization_id !== 'string' || !reference(current.organization_id))) throw new Error('invalid');
  if (!custodyStates.includes(row.state as CustodyRecord['state']) || !['private','dealer','brand','job'].includes(String(row.route)) || typeof row.held !== 'boolean' || row.watch_id !== current.watch_id || typeof row.custodian !== 'string' || !reference(row.custodian) || typeof row.operation_id !== 'string' || !reference(row.operation_id)) throw new Error('invalid');
  for (const field of ['buyer_received_at','dispute_deadline','next_review_at']) if (row[field] !== null && !utc(row[field])) throw new Error('invalid');
  if (row.pending_reason !== null && typeof row.pending_reason !== 'string') throw new Error('invalid');
  if (row.next_actor !== null && (typeof row.next_actor !== 'string' || !reference(row.next_actor))) throw new Error('invalid');
  if (row.held && (!row.pending_reason || !row.next_actor || !row.next_review_at)) throw new Error('invalid');
  if (!Array.isArray(row.due_actions) || row.due_actions.length > 6 || row.due_actions.some(action=>!object(action) || typeof action.code !== 'string' || !utc(action.due_at) || typeof action.next_actor !== 'string' || !reference(action.next_actor))) throw new Error('invalid');
  if (row.buyer_received_at !== null) {
    const hours = row.route === 'private' ? 72 : 168;
    if (row.window_hours !== hours || !utc(row.dispute_deadline) || Date.parse(String(row.dispute_deadline)) - Date.parse(String(row.buyer_received_at)) !== hours * 3600000) throw new Error('invalid');
  } else if (row.dispute_deadline !== null || row.window_hours !== null || row.state === 'received') throw new Error('invalid');
  return row as unknown as CustodyRecord;
}

export function buyerCommand(record:CustodyRecord, proof:ReceiptProof, operation:string):BuyerReceiptCommand {
  if (!reference(operation) || proof.accessories.length > 50 || Object.values(proof).some(value=>typeof value === 'string' && (!value.length || value.length > 1000)) || proof.accessories.some(value=>!value.length || value.length > 100)) throw new Error('invalid');
  return {...record.current,schema_version:custodyVersion,subject_id:record.subject_id,operation_id:operation,expected_revision:record.revision,action:'buyer_receipt',proof};
}

export function decodeHistory(value:unknown, order:string, offset:number):CustodyHistory {
  if (!object(value) || value.schema_version !== custodyVersion || !object(value.result)) throw new Error('invalid');
  const result = value.result;
  if (result.subject_id !== order || result.offset !== offset || result.limit !== 25 || !integer(result.total) || !Array.isArray(result.items) || result.items.length > 25 || result.items.length > Number(result.total)) throw new Error('invalid');
  let revision = Infinity;
  for (const row of result.items) {
    if (!object(row) || typeof row.operation_id !== 'string' || !reference(row.operation_id) || !integer(row.revision) || Number(row.revision) >= revision || !custodyStates.includes(row.state as CustodyRecord['state']) || typeof row.held !== 'boolean') throw new Error('invalid');
    for (const field of ['buyer_received_at','dispute_deadline']) if (row[field] !== null && !utc(row[field])) throw new Error('invalid');
    revision = Number(row.revision);
  }
  return result as unknown as CustodyHistory;
}
