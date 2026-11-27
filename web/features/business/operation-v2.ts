import { businessRequest } from './transport';
import type { BusinessResult } from '@contracts/contracts-identity/businesses/workspace_v2';

/** A mounted form owns an immutable request until its outcome is known. */
export class BusinessOperation {
  readonly id = crypto.randomUUID();
  private request: { path: string; body: string } | null = null;
  private generation = 0;
  private submission: (() => Promise<BusinessResult>) | null = null;
  retainSubmission(submit: () => Promise<BusinessResult>) {
    if (!this.active) throw new Error('access_changed');
    this.submission ??= submit;
  }
  async replay() {
    if (!this.active) throw new Error('access_changed');
    const generation = this.generation;
    const result = await (this.submission ? this.submission() : this.retry());
    this.current(generation);
    return result;
  }
  private legacy: {path:string; body:string; method:string} | null = null;
  private active = true;
  private upload: { file: File; binding: string; reference?: string } | null = null;
  dispose() { this.active = false; this.generation++; this.upload = null; this.request = null; this.legacy = null; this.submission = null; }
  private current(generation: number) {
    if (!this.active || generation !== this.generation) throw new Error('access_changed');
  }
  async membership(path: string, body: Record<string, unknown>, method = 'POST'): Promise<BusinessResult> {
    if (!this.active) throw new Error('access_changed');
    const generation = this.generation;
    const serialized = JSON.stringify(body);
    if (this.legacy && (this.legacy.path !== path || this.legacy.body !== serialized || this.legacy.method !== method))
      throw new Error('operation_conflict');
    this.legacy ??= {path, body:serialized, method};
    const result = await businessRequest<{revision:number; state:BusinessResult['state']}>(path, {
      method, headers:{'Idempotency-Key':this.id}, body:serialized,
    });
    this.current(generation);
    return this.result({...result, operation_id:this.id, operation_state:'committed'});
  }
  async photo(file: File, binding: Record<string, string>) {
    if (!this.active) throw new Error('access_changed');
    const generation = this.generation;
    const serialized = JSON.stringify(binding);
    if (this.upload && (this.upload.file !== file || this.upload.binding !== serialized))
      throw new Error('operation_conflict');
    this.upload ??= { file, binding: serialized };
    if (this.upload.reference) return this.upload.reference;
    const data = new FormData();
    data.set('photo', file);
    Object.entries(binding).forEach(([key, value]) => data.set(key, value));
    const result = await businessRequest<{ evidence_ref: string }>('/v2/listing-possession/photos', {
      method: 'POST', headers: { 'Idempotency-Key': `${this.id}:photo` }, body: data,
    });
    this.current(generation);
    if (typeof result.evidence_ref !== 'string' || !result.evidence_ref) throw new Error('invalid_response');
    this.upload.reference = result.evidence_ref;
    return result.evidence_ref;
  }
  async send(path: string, body: Record<string, unknown>) {
    if (!this.active) throw new Error('access_changed');
    const generation = this.generation;
    const serialized = JSON.stringify({ ...body, operation_id: this.id, schema_version: 'identity.business.v2' });
    if (this.request && (this.request.path !== path || this.request.body !== serialized))
      throw new Error('operation_conflict');
    this.request ??= { path, body: serialized };
    const result = await businessRequest<BusinessResult>(this.request.path, {
      method: 'POST', headers: { 'Idempotency-Key': this.id }, body: this.request.body,
    });
    this.current(generation);
    return this.result(result);
  }
  private result(result: BusinessResult) {
    if (!['pending','committed'].includes(result.operation_state) || result.operation_id !== this.id || !Number.isInteger(result.revision) || result.revision < 1
      || !['issued','pending','approved','correction','rejected','suspended','active','revoked'].includes(result.state))
      throw new Error('invalid_response');
    return result;
  }
  async retry() {
    if (this.legacy) return this.membership(this.legacy.path, JSON.parse(this.legacy.body), this.legacy.method);
    if (!this.request) throw new Error('request_unavailable');
    return this.send(this.request.path, JSON.parse(this.request.body));
  }
  async recover(): Promise<BusinessResult> {
    if (this.legacy) return this.retry();
    if (!this.active) throw new Error('access_changed');
    const generation = this.generation;
    const result = await businessRequest<BusinessResult>(`/v2/business-operations/${this.id}`);
    this.current(generation);
    return this.result(result);
  }
}
