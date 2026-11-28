import type { TwoFactorResult, SensitiveAction } from '@contracts/contracts-identity/two-factor/current';
import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';

export type Status = { schema_version: 1; revision: number; state: 'empty' | 'enrolling' | 'enabled' | 'pending' };
export type FactorCommand = {
  schema_version: 1; operation_id: string; expected_revision: number;
  kind: 'enroll' | 'confirm' | 'prove'; proof?: string; current_password?: string;
  action?: SensitiveAction; record_id?: string; record_revision?: number; organization_id?: string | null;
};
const base = '/api/web/v1/identity/v1/two-factor';
export const statusRead = definePageRead({
  key: (fingerprint: string) => ['two-factor-status-v1', fingerprint],
  warm: 'open-only', fresh: 0,
  ask: async (signal, fingerprint: string): Promise<Status> => {
    const result = await authenticatedRequest<Status>(base, {signal, accessFingerprint: fingerprint});
    if (result.schema_version !== 1 || !Number.isSafeInteger(result.revision) || result.revision < 0 ||
        !['empty', 'enrolling', 'enabled', 'pending'].includes(result.state)) throw new Error('unavailable');
    return {schema_version: 1, revision: result.revision, state: result.state};
  },
});
export async function submitFactor(command: FactorCommand, fingerprint: string): Promise<TwoFactorResult> {
  const result = await authenticatedRequest<TwoFactorResult>(base, {
    method: 'POST', accessFingerprint: fingerprint,
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(command),
  });
  if (result.schema_version !== 1 || result.operation_id !== command.operation_id ||
      !Number.isSafeInteger(result.revision) || result.revision !== command.expected_revision + 1 ||
      !['enrolling', 'enabled', 'proved', 'pending', 'sign_in_required'].includes(result.state)) throw new Error('unavailable');
  if (result.state !== 'pending') {
    if (command.kind === 'enroll' && (result.state !== 'enrolling' || !/^[A-Z2-7]{32}$/.test(result.secret ?? ''))) throw new Error('unavailable');
    if (command.kind === 'confirm' && (result.state !== 'enabled' || result.recovery_codes?.length !== 10 ||
        !result.recovery_codes.every(code=>/^[0-9a-f]{32}$/.test(code)))) throw new Error('unavailable');
    if (command.kind === 'prove' && (result.state !== 'proved' || !result.proof_id || !result.expires_at)) throw new Error('unavailable');
  }
  return result;
}
