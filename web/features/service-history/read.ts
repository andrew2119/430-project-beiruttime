import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
import type { HistoryResult } from '@contracts/contracts-service/history';
export type Selection = {watch:string;revision:number;page:number;operation:string};
export const historyRead = definePageRead({
  key:(fingerprint:string, selection:Selection)=>['service-history.v1',fingerprint,selection.watch,selection.revision,selection.page,selection.operation],
  warm:'open-only',fresh:0,
  ask:(signal:AbortSignal,fingerprint:string,selection:Selection)=>authenticatedRequest<HistoryResult>(`/api/web/v1/service-operations/v1/history/${encodeURIComponent(selection.watch)}?operation_id=${selection.operation}&expected_revision=${selection.revision}&page=${selection.page}&page_size=20`,{signal,accessFingerprint:fingerprint}),
});
export function validSelection(watch:string,revision:string) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(watch) && /^(0|[1-9][0-9]{0,8})$/.test(revision);
}
