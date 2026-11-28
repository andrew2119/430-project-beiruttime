/** Synchronous access events fence private bytes before a render can commit. */
export class ExportFence {
  private active=true;
  private controller:AbortController|null=null;
  constructor(private events:EventTarget) {events.addEventListener('bt:access-change',this.revoke);}
  private revoke=()=>{this.active=false;this.controller?.abort();};
  begin() {
    if (!this.active || this.controller)return null;
    this.controller=new AbortController();
    return this.controller;
  }
  accepts(controller:AbortController) {return this.active && this.controller===controller && !controller.signal.aborted;}
  finish(controller:AbortController) {if(this.controller===controller)this.controller=null;}
  dispose() {this.revoke();this.events.removeEventListener('bt:access-change',this.revoke);}
}
