import type { MaintenanceRequestV1, MaintenanceResultV1 } from '@contracts/contracts-service/maintenance/v1';
export type PreparedPhoto={operation_id:string;media_type:string;content_base64:string};
export type RequestTransport={upload:(photo:PreparedPhoto,body:MaintenanceRequestV1,signal:AbortSignal)=>Promise<unknown>;lookup?:(body:MaintenanceRequestV1,signal:AbortSignal)=>Promise<MaintenanceResultV1>;submit:(body:MaintenanceRequestV1,signal:AbortSignal)=>Promise<MaintenanceResultV1>};
export function receiptBinding(body:MaintenanceRequestV1) {
  const {schema_version,operation_id,actor_id,subject_id,organization_id,watch_id,
    expected_revision,watch_revision,capability_revision,policy_revision,brand_id,intervention}=body;
  return {schema_version,operation_id,actor_id,subject_id,organization_id,watch_id,
    expected_revision,watch_revision,capability_revision,policy_revision,brand_id,intervention};
}
export type ReceiptBinding=ReturnType<typeof receiptBinding>;

export function matchesReceipt(result:MaintenanceResultV1,binding:ReceiptBinding) {
  return Object.entries(binding).every(([key,value])=>result[key as keyof ReceiptBinding]===value);
}
export function isReference(value: unknown): value is string {
  return typeof value === 'string' && value.length === 36 &&
    /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value);
}
export function validResultReceipt(result:MaintenanceResultV1) {
  switch(result.state) {
    case 'submitted': return result.revision===1 && isReference(result.request_id);
    case 'denied':
    case 'stale':
    case 'pending': return result.revision===0;
    default: return false;
  }
}
export function uploadReceiptBinding(photo: PreparedPhoto, body: MaintenanceRequestV1) {
  const {actor_id, subject_id, organization_id, watch_id, brand_id, intervention,
    watch_revision, capability_revision, policy_revision} = body;
  return {operation_id: photo.operation_id, request_operation_id: body.operation_id,
    actor_id, subject_id, organization_id, watch_id, brand_id, intervention,
    watch_revision, capability_revision, policy_revision, revision: 1};
}

function acknowledgedPhoto(answer: unknown, photo: PreparedPhoto, body: MaintenanceRequestV1) {
  if (!answer || typeof answer !== 'object') throw new Error('response_scope');
  const receipt = answer as Record<string, unknown>;
  if (!isReference(receipt.photo_ref) || !Object.entries(uploadReceiptBinding(photo, body))
    .every(([field, value]) => receipt[field] === value)) throw new Error('response_scope');
  return receipt.photo_ref;
}

export function isMissingReceipt(error:unknown) {
  return typeof error==='object'&&error!==null&&'status' in error&&error.status===404
    &&'code' in error&&error.code==='operation_missing';
}
export class ContextReviewRequired extends Error {}
/** A lost response retains both the submission reference and acknowledged uploads. */
export class Submission {
  private references:string[]=[];
  private attempted=false;
  private refreshPhotos=false;
  readonly bindings:readonly MaintenanceRequestV1[];
  constructor(readonly body:MaintenanceRequestV1,private preparedPhotos:readonly PreparedPhoto[],previous:readonly MaintenanceRequestV1[]=[] ) {
    if(previous.length>=100)throw new ContextReviewRequired('context_review_limit');
    if(previous.some(item=>item.operation_id!==body.operation_id||item.actor_id!==body.actor_id||item.subject_id!==body.subject_id||item.watch_id!==body.watch_id))throw new Error('response_scope');
    this.bindings=[body,...previous];
  }
  get photos() {
    return this.preparedPhotos;
  }
  get requestAttempted() {
    return this.attempted;
  }
  get reviewLimitReached() {
    return this.bindings.length >= 100;
  }
  revise(body:MaintenanceRequestV1) {
    if(body.organization_id!==this.body.organization_id)throw new Error('response_scope');
    const scopeChanged = (['brand_id', 'intervention', 'watch_revision', 'capability_revision', 'policy_revision'] as const)
      .some(field => body[field] !== this.body[field]);
    const photos = scopeChanged
      ? this.photos.map(photo => ({...photo, operation_id: crypto.randomUUID()}))
      : this.photos;
    const next = new Submission(body, photos, this.bindings);
    if (!scopeChanged) next.references = [...this.references];
    next.attempted = this.attempted;
    next.refreshPhotos = !scopeChanged && this.refreshPhotos;
    return next;
  }
  private async lookup(find:NonNullable<RequestTransport['lookup']>,signal:AbortSignal) {
    const organizations=new Set<string>();
    for(const binding of this.bindings) {
      if(signal.aborted)throw new Error('access_changed');
      if(organizations.has(binding.organization_id))continue;
      organizations.add(binding.organization_id);
      try {return await find(binding,signal);} catch(error) {
        if(!isMissingReceipt(error))throw error;
      }
    }
  }
  async run(transport:RequestTransport,signal:AbortSignal) {
    if(signal.aborted)throw new Error('access_changed');
    if(this.refreshPhotos&&!transport.lookup)throw new Error('receipt_lookup_required');
    const recovered=this.attempted&&transport.lookup?await this.lookup(transport.lookup,signal):undefined;
    if(signal.aborted)throw new Error('access_changed');
    let result:MaintenanceResultV1;
    try {
      if (recovered) {
        result = recovered;
      } else {
        if(this.refreshPhotos) {
          this.preparedPhotos=this.photos.map(photo=>({...photo,operation_id:crypto.randomUUID()}));
          this.references=[];
          this.refreshPhotos=false;
        }
        for(let index=this.references.length;index<this.photos.length;index++) {
          if(signal.aborted)throw new Error('access_changed');
          const answer = await transport.upload(this.photos[index], this.body, signal);
          if (signal.aborted) throw new Error('access_changed');
          const reference = acknowledgedPhoto(answer, this.photos[index], this.body);
          if (this.references.includes(reference)) throw new Error('response_scope');
          this.references.push(reference);
        }
        if(signal.aborted)throw new Error('access_changed');
        this.attempted=true;
        result=await transport.submit({...this.body,photo_refs:[...this.references]},signal);
      }
    } catch(error) {
      if(signal.aborted)throw new Error('access_changed');
      if(!this.attempted||!transport.lookup||typeof error!=='object'||error===null||!('status' in error)||error.status!==409)throw error;
      const photosUnavailable='code' in error && error.code === 'photo_unavailable' && this.photos.length>0;
      if (photosUnavailable) this.refreshPhotos=true;
      const recovered=await this.lookup(transport.lookup,signal);
      if (!recovered) {
        if (photosUnavailable) throw error;
        if ('code' in error && error.code === 'watch_committed') throw error;
        throw new ContextReviewRequired('review_current_context');
      }
      result=recovered;
    }
    if(signal.aborted)throw new Error('access_changed');
    if(!validResultReceipt(result)||!this.bindings.some(binding=>
      matchesReceipt(result,receiptBinding(binding))))throw new Error('response_scope');
    return result;
  }
}

export function validPhotos(files:readonly Pick<File,'size'|'type'>[]):boolean {
  return files.length<=10&&files.every(file=>file.size>=1&&file.size<=262144&&['image/jpeg','image/png','image/webp'].includes(file.type));
}
