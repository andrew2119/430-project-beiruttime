import type { Command, Receipt } from '@contracts/contracts-comms/messages';
export type Transport = {send:(body:Command)=>Promise<Receipt>;lookup:(operation:string)=>Promise<Receipt|{state:'pending'}>};
/** One bounded reconciliation, then one identical retry. The caller retains bytes on uncertainty. */
export async function reconcile(body:Command, transport:Transport):Promise<Receipt> {
  try {return await transport.send(body);} catch(error) {
    if (typeof error === 'object' && error !== null && 'status' in error && typeof error.status === 'number' && error.status < 500) throw error;
    const found = await transport.lookup(body.operation_id);
    if (found.state === 'accepted') return found;
    return transport.send(body);
  }
}

/** Retain uncertainty across attempts until the original receipt is available. */
export class PendingCommand {
  uncertain = false;
  constructor(readonly body:Command) {}

  async run(transport:Transport):Promise<Receipt> {
    if (this.uncertain) {
      const found = await transport.lookup(this.body.operation_id);
      if (found.state === 'accepted') return found;
    }
    return reconcile(this.body, {
      lookup:transport.lookup,
      send:async body=>{
        try {return await transport.send(body);} catch(error) {
          const definitive = typeof error === 'object' && error !== null && 'status' in error && typeof error.status === 'number' && error.status < 500;
          if (!definitive) this.uncertain = true;
          throw error;
        }
      }
    });
  }
}
