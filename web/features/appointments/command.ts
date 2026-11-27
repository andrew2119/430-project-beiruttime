import type { Command, Visit } from '@contracts/contracts-service/appointments';

/** One in-memory immutable request survives an uncertain response and language changes. */
export class VisitCommand {
  pending:Command|null = null;
  result:Visit|null = null;
  begin(command:Command) {
    if (this.pending) return this.pending;
    this.pending = Object.freeze({...command});
    return this.pending;
  }
  acknowledge(visit:Visit) {
    if (!this.pending || visit.operation_id !== this.pending.operation_id || visit.appointment_id !== this.pending.appointment_id) {
      throw new Error('operation_mismatch');
    }
    this.result = visit;
    this.pending = null;
  }
  reject() { this.pending = null; }
  clear() { this.pending = null; this.result = null; }
}
