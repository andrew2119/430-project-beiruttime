import { authenticatedRequest } from '@/features/identity/session';
import { definePageRead } from '@/lib/page-speed/definition';
import type { Current, Command } from '../../../packages/contracts-service/brand-assessment/v1';
const base = '/api/web/v1/service-operations/v1/brand-assessments';
export const assessmentRead = definePageRead({
  key: (id: string) => ['brand-assessment.v1', id], warm: 'open-only', fresh: 0,
  ask: (signal: AbortSignal, id: string) => authenticatedRequest<Current>(`${base}/${encodeURIComponent(id)}`, { signal }),
});
export function submit(command: Command) {
  return authenticatedRequest<Current>(`${base}/${encodeURIComponent(command.subject_id)}/commands`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(command),
  });
}

export function lookupOperation(subject: string, operation: string) {
  return authenticatedRequest<Current>(`${base}/${encodeURIComponent(subject)}/operations/${encodeURIComponent(operation)}`);
}
