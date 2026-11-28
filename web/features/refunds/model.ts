import { normalizeDigits } from '@beirut-time/i18n';
import type { RefundCode, RefundCommand, RefundOperation } from '@contracts/contracts-orders/refunds';

export type Binding = Omit<RefundCommand,'operation_id'|'amount_minor'|'currency'|'schema_version'>;
export type RefundRead = Readonly<{binding:Binding;remaining_minor:number}>;
export interface RefundPort {
  current(signal:AbortSignal):Promise<RefundRead>;
  request(command:RefundCommand,signal:AbortSignal):Promise<RefundOperation>;
  lookup(command:RefundCommand,signal:AbortSignal):Promise<RefundOperation|null>;
}
export class RefundFailure extends Error {
  constructor(readonly code:RefundCode,readonly noEffect=false) { super(code); }
}
export const unavailablePort:RefundPort = {
  current:async()=>{throw new RefundFailure('unavailable');},
  request:async()=>{throw new RefundFailure('unavailable');},
  lookup:async()=>{throw new RefundFailure('unavailable');},
};
export function dollarsToMinor(input:string):number|null {
  const normalized=normalizeDigits(input.trim()).replace('٫','.');
  if (!/^(0|[1-9][0-9]{0,13})(\.[0-9]{1,2})?$/.test(normalized)) return null;
  const [whole,fraction='']=normalized.split('.');
  const minor=BigInt(whole)*100n+BigInt(fraction.padEnd(2,'0'));
  return minor>0n && minor<=9000000000000000n ? Number(minor) : null;
}
/** Kept by the mounted form across language changes, only in memory. */
export class RefundDraft {
  amount='';
  command:RefundCommand|null=null;
  operation:RefundOperation|null=null;
  code:RefundCode|null=null;
  busy=false;
  rejected=false;
  private effectPossible=false;
  private listeners=new Set<()=>void>();
  private snapshot={amount:this.amount,command:this.command,operation:this.operation,code:this.code,busy:this.busy,rejected:this.rejected};
  subscribe=(listener:()=>void)=>{this.listeners.add(listener);return ()=>{this.listeners.delete(listener);};};
  read=()=>this.snapshot;
  private publish() {
    this.snapshot={amount:this.amount,command:this.command,operation:this.operation,code:this.code,busy:this.busy,rejected:this.rejected};
    this.listeners.forEach(listener=>listener());
  }
  setAmount(value:string) {if (!this.command && !this.busy) {this.amount=value;this.publish();}}
  begin(binding:Binding,id:string) {
    if (this.busy || this.rejected) return null;
    const command=this.prepare(binding,id);
    if (command) {this.busy=true;this.publish();}
    return command;
  }
  fail(code:RefundCode,noEffect=false) {
    this.code=code;
    this.rejected=noEffect && !this.effectPossible && !this.operation &&
      ['denied','stale','basis_required','return_required','cap_exceeded'].includes(code);
    if (!this.rejected) this.effectPossible=true;
    this.publish();
  }
  reviewRejected() {
    if (!this.rejected || this.busy) return;
    this.command=null;this.code=null;this.rejected=false;this.publish();
  }
  finish() {this.busy=false;this.publish();}
  reset() {
    if (this.operation?.state!=='confirmed' && this.operation?.state!=='declined') return;
    this.amount='';this.command=null;this.operation=null;this.code=null;this.effectPossible=false;this.rejected=false;this.publish();
  }
  prepare(binding:Binding,id:string) {
    if (this.command) return this.command;
    const minor=dollarsToMinor(this.amount);
    if (minor===null) return null;
    this.command=Object.freeze({...binding,operation_id:id,amount_minor:minor,currency:'USD',schema_version:'refunds.v1'});
    return this.command;
  }
  accept(value:RefundOperation) {
    const command=this.command;
    if (!command || ['operation_id','subject_id','watch_id','actor_id','organization_id','expected_revision','amount_minor']
      .some(key=>value[key as keyof RefundOperation]!==command[key as keyof RefundCommand]) ||
      value.schema_version!=='refunds.v1' || value.currency!=='USD' || value.simulated!==true ||
      !['pending','confirmed','declined'].includes(value.state) || !Number.isSafeInteger(value.revision) ||
      value.revision<=command.expected_revision ||
      (value.state!=='pending' && (value.pending_reason!==null || value.next_actor!==null || value.next_review_at!==null)) ||
      (value.state==='pending' && (!['processing','reconciliation'].includes(value.pending_reason ?? '') || value.next_actor!=='payout_operator' ||
        !value.next_review_at || !Number.isFinite(Date.parse(value.next_review_at))))) {
      throw new RefundFailure('unavailable');
    }
    this.effectPossible=true;
    this.rejected=false;
    this.operation=value;
    this.code=null;
    this.publish();
  }
}
