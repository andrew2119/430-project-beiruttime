export type TransferCommand = Readonly<{
  operation_id: string; actor_id: string; organization_id: string;
  subject_id: string; watch_id: string; sale_id: string;
  expected_revision: number; source_revision: number; quote_revision: number; policy_revision: number;
}>;
export type TransferState = 'empty' | 'pending' | 'transferred' | 'denied' | 'stale' | 'conflict' | 'duplicate' | 'unavailable';
export type TransferResult = {
  schema_version: 'resale-records.v1'; operation_id: string;
  actor_id: string; organization_id: string; subject_id: string; watch_id: string; expected_revision: number;
  pending_reason: string | null; next_actor: string; next_review_at: string | null;
  state: Exclude<TransferState, 'empty' | 'unavailable'>; revision: number | null;
};
export type TransferBoundary = {
  transfer: (command: TransferCommand, signal: AbortSignal) => Promise<TransferResult>;
};
/** The pending reference and bindings stay identical across language changes and retries. */
export function beginTransfer(command: Omit<TransferCommand, 'operation_id'>, operationId: string): TransferCommand {
  return Object.freeze({ ...command, operation_id: operationId });
}
export function acceptsResult(command: TransferCommand, result: TransferResult): boolean {
  return result.schema_version === 'resale-records.v1' && result.operation_id === command.operation_id
    && result.actor_id === command.actor_id && result.organization_id === command.organization_id
    && result.subject_id === command.subject_id && result.watch_id === command.watch_id
    && result.expected_revision === command.expected_revision
    && ['pending', 'transferred', 'denied', 'stale', 'conflict', 'duplicate'].includes(result.state)
    && (result.state !== 'transferred' || (Number.isSafeInteger(result.revision) && result.revision === command.expected_revision + 1));
}
