import { definePageRead } from '@/lib/page-speed/definition';
import { call } from '../common';
import type { AssessmentCustodyV1, IntakeCommandV1, OpeningAcceptanceV1 } from '@contracts/contracts-service/intake/v1';
export type Summary={id:string;order_id:string;revision:number;state:string};
export type Detail=Summary & {private_record:Omit<IntakeCommandV1,'order_id'|'custody_receipt_id'|'reviewed_assessment_custody'|'reviewed_receipt_revision'>;custody_receipt_id:string|null;diagnosis_allowed:boolean;assessment_allowed?:boolean;current_assessment_custody?:AssessmentCustodyV1;receipt_revision_for_review?:AssessmentCustodyV1;current_opening_acceptance?:OpeningAcceptanceV1;current_opening_fee_minor?:number;custody_verification:'checking'|'awaiting_intake'|'current'|'unconfirmed'|'unavailable'};
export const intakeRead=definePageRead({key:(scope:string,organization:string,offset:number,generation:string)=>['maintenance-intake',scope,organization,offset,generation],warm:'open-only',fresh:0,
  async ask(signal:AbortSignal,scope:string,organization:string,offset:number) {
    const queue=await call<{intake_contract?:unknown;items:Summary[];total:number;next_offset:number|null}>(
      scope,`intake/records?organization_id=${encodeURIComponent(organization)}&offset=${offset}`,{signal});
    if(queue.intake_contract!=='current'||!Array.isArray(queue.items)||!Number.isSafeInteger(queue.total)||queue.total<0||
      (queue.next_offset!==null&&queue.next_offset!==offset+50))throw new Error('intake_contract_unavailable');
    return queue;
  }});
export const detailRead=definePageRead({key:(scope:string,organization:string,id:string,generation:string)=>['maintenance-intake-detail',scope,organization,id,generation],warm:'open-only',fresh:0,
  ask:(signal:AbortSignal,scope:string,organization:string,id:string)=>call<Detail>(scope,`intake/records/${encodeURIComponent(id)}?organization_id=${encodeURIComponent(organization)}`,{signal})});
