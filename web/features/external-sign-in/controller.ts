import type { ExternalOperation } from '@contracts/contracts-identity/external-sign-in';

export type Transport = (operation: Readonly<ExternalOperation>, signal: AbortSignal) => Promise<ExternalOperation>;

/** A late answer cannot cross an access boundary or replace the operation. */
export class OperationController {
  private generation = 0;
  private active: AbortController | null = null;
  constructor(private readonly transport: Transport) {}
  clear() { this.generation++; this.active?.abort(); this.active = null; }
  async retry(operation: ExternalOperation): Promise<ExternalOperation | null> {
    this.clear();
    const generation = this.generation;
    const request = new AbortController();
    this.active = request;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const result = await Promise.race([
        this.transport(Object.freeze({...operation}), request.signal),
        new Promise<never>((_, reject) => { timer = setTimeout(() => { request.abort(); reject(new Error('unavailable')); }, 2000); }),
      ]);
      if (generation !== this.generation || request.signal.aborted) return null;
      if (result.schema_version !== 1 || result.operation_id !== operation.operation_id ||
          result.actor_id !== operation.actor_id || result.organization_id !== operation.organization_id ||
          result.expected_revision !== operation.expected_revision || !Number.isSafeInteger(result.revision) ||
          result.revision < operation.revision ||
          (result.state === 'linked' && result.subject_id !== operation.actor_id) ||
          !['ready','pending','signed_in','linked','denied','stale','unavailable'].includes(result.state)) {
        throw new Error('unavailable');
      }
      return result;
    } catch {
      if (generation !== this.generation) return null;
      return {...operation, state: 'pending', subject_id: null, pending_reason: 'identity_unavailable', next_actor: 'identity'};
    } finally {
      if (timer !== undefined) clearTimeout(timer);
      if (generation === this.generation) this.active = null;
    }
  }
}
