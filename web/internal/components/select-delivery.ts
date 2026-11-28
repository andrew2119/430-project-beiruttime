export function createDeliveryGate() {
  type Phase = 'idle'|'waiting'|'failed'|'released'|'closed';
  let phase:Phase = 'idle', pending:{promise:Promise<void>;resolve:()=>void;reject:(reason:Error)=>void}|undefined;
  const listeners = new Set<()=>void>(), publish = (next:Phase)=>{phase = next;for (const listener of listeners) listener();};
  const wait = ()=>{
    if (pending) return pending.promise;
    let resolve!:()=>void, reject!:(reason:Error)=>void;
    const promise = new Promise<void>((done,fail)=>{resolve = done;reject = fail;});pending = {promise,resolve,reject};publish('waiting');return promise;
  };
  return {wait,current:()=>phase,server:():Phase=>'idle',subscribe:(listener:()=>void)=>{listeners.add(listener);return ()=>listeners.delete(listener);},
    release:()=>{if (!pending) return;const job = pending;pending = undefined;publish('released');job.resolve();},
    fail:()=>{if (!pending) return;const job = pending;pending = undefined;publish('failed');job.reject(new Error('Local options delivery rejected.'));},
    dispose:()=>{const job = pending;pending = undefined;listeners.clear();phase = 'closed';job?.reject(new Error('Local options delivery closed.'));},
  };
}
