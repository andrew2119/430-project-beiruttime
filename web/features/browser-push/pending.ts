import type { PushCommand, PushResult } from '@contracts/contracts-comms/browser-push';
/** Retain the exact in-memory request across uncertain responses and language changes. */
export class PendingOperation {
  private body:PushCommand|null=null;
  private flight:Promise<PushResult>|null=null;
  constructor(private readonly send:(body:PushCommand)=>Promise<PushResult>) {}
  clear() {this.body=null;}
  run(command:PushCommand):Promise<PushResult> {
    if (this.flight) return this.flight;
    if (this.body && JSON.stringify(this.body)!==JSON.stringify(command)) return Promise.reject(new Error('pending'));
    if (!this.body) this.body=structuredClone(command);
    const retained=this.body;
    this.flight=this.send(structuredClone(retained)).then(result=>{if(this.body===retained)this.body=null;return result;}).finally(()=>{this.flight=null;});
    return this.flight;
  }
}
