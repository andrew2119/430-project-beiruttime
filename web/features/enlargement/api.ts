import { authenticatedRequest } from '@/features/identity/session';
import { definePageRead } from '@/lib/page-speed/definition';
export type RecordView = {
  request_id:string; watch_id:string; organization_id:string; source_revision:number; revision:number;
  state:'requested'|'assessed'|'waiting'|'accepted'|'worked'|'fit_recorded'|'rework';
  assessment?:{target:string;limitations:string;total_minor:number;quote_id:string;quote_revision:number;terms_revision:number;parts:{id:string;revision:number;kind:'links'|'strap'|'clasp';status:'supplied'|'ordered'|'available'|'unavailable';quantity:number}[]};
  request?:{measurement:string;unit:'cm'|'mm';measurement_mm:string;method:string;source:string;target:string;choice:'links'|'strap'|'clasp'};
  responsible_operator_id?:string;
  next_action?:{en:string;ar:string};
  first_response_due_at?:string;
  escalation_at?:string;
  next_review_at?:string|null;
  quality?:{fit:string};
  allowed_operations?:string[];
  quote_lines?:{id:string;label_en:string;label_ar:string;amount_minor:number}[];
  quote_terms?:{en:string;ar:string};
};
export const endpoint = '/api/web/v1/service-operations/v1/enlargement';
export const enlargementRead = definePageRead({
  key:(id:string)=>['enlargement.v1',id], warm:'open-only',fresh:0,
  ask:(signal:AbortSignal,id:string)=>authenticatedRequest<RecordView>(`${endpoint}/requests/${encodeURIComponent(id)}`,{signal}),
});
export function submit(body:object) {
  return authenticatedRequest<RecordView>(`${endpoint}/commands`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}
