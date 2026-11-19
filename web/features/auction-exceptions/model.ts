import type { Action, Command, Context, Receipt } from '@contracts/contracts-trust/auction-exceptions/current';
export type Draft = {action: Action; reason: string; target: string; command: Command | null; receipt: Receipt | null; rejection?: 'denied' | 'error'};
export const initialDraft: Draft = {action:'cancel', reason:'', target:'', command:null, receipt:null};
export function prepare(draft: Draft, context: Context, operation: string): Draft {
  if (draft.command) return draft;
  return {...draft, command:{...context, operation_id:operation, action:draft.action, reason:draft.reason,
    target_bidder_id:draft.action === 'retract' || draft.action === 'remove_bid' ? draft.target : null}};
}
export function boundReceipt(command: Command, receipt: Receipt): boolean {
  return receipt.schema_version === 'auction-exceptions.v1' &&
    ['pending','denied','acknowledged'].includes(receipt.state) &&
    Number.isSafeInteger(receipt.revision) && receipt.revision >= 0 && (receipt.revision >= command.expected_revision || (receipt.state === 'denied' && receipt.code === 'stale_revision')) &&
    (['operation_id','subject_id','watch_id','actor_id','organization_id','expected_revision','quote_id','quote_revision','policy_revision','assignment_revision'] as const)
      .every(key => command[key] === receipt[key]);
}

export function newRequest(draft: Draft): Draft {
  return draft.receipt?.state === 'denied' || draft.rejection ? {...draft, command:null, receipt:null, rejection:undefined} : draft;
}

// Only a definitive, operation-bound rejection permits a fresh request.
export class SubmissionRejected extends Error {
  constructor(public operation_id: string, public code: 'invalid_request' | 'permission_denied') {
    super(code);
  }
}
export function rejected(draft: Draft, error: unknown): Draft {
  return error instanceof SubmissionRejected && error.operation_id === draft.command?.operation_id
    ? {...draft, rejection:error.code === 'permission_denied' ? 'denied' : 'error'} : draft;
}
export function validReason(reason: string): boolean {
  const trimmed = reason.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/gu, '');
  const length = Array.from(trimmed).length;
  return length >= 10 && length <= 2000;
}
