/** A pending indication is not a minimum navigation duration. Commit/unmount
 * cancels the task, including a queued callback from an older attempt. */
export function delayedPending(delay:number,show:()=>void,schedule:(run:()=>void,ms:number)=>unknown = setTimeout,cancel:(handle:unknown)=>void = handle=>clearTimeout(handle as ReturnType<typeof setTimeout>)) {
  let active = true;
  const timer = schedule(()=>{if (active) show();},delay);
  return ()=>{active = false;cancel(timer);};
}
