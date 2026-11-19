import { authenticatedRequest } from '@/features/identity/session';
import { definePageRead } from '@/lib/page-speed/definition';

export type Verdict = 'passed'|'failed'|'inconclusive';
export type Workspace = {
  schema_version:'private-inspection.v1'; subject_id:string; watch_id:string; watch_revision:number;
  actor_id:string; organization_id:string; assignment_revision:number; quote_id:string; quote_revision:number;
  policy_revision:number; source_revision:number; expected_revision:number; custody_receipt_id:string;
  checklist_revision:number; evidence_refs:string[]; current_state:Verdict|null;
};
export type Receipt = {operation_id:string;state:Verdict;revision:number};
export type Command = Omit<Workspace,'current_state'> & {operation_id:string;checklist:{item:string;verdict:Verdict}[];result:Verdict;reason:string};
const base = '/api/web/v1/trust/v1/private-inspections';
export const inspectionRead = definePageRead({
  key:(access:string,subject:string)=>['private-inspection.v1',access,subject],
  ask:(signal:AbortSignal,access:string,subject:string)=>authenticatedRequest<Workspace>(`${base}/${encodeURIComponent(subject)}/workspace`,{signal,accessFingerprint:access}),
  warm:'open-only',fresh:0,
});
export function submitInspection(access:string,command:Command) {
  return authenticatedRequest<Receipt>(`${base}/results`,{method:'POST',accessFingerprint:access,
    headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});
}
export function deriveResult(values:Verdict[]):Verdict {
  return values.includes('failed')?'failed':values.includes('inconclusive')?'inconclusive':'passed';
}

export function sameWorkspace(reviewed:Workspace,current:Workspace):boolean {
  return (Object.keys(reviewed) as (keyof Workspace)[]).every(key=>
    JSON.stringify(reviewed[key]) === JSON.stringify(current[key]));
}
