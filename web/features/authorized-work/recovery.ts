import type { Attempt } from './form';

type Receipt = {operation_id:string;state:'recorded'|'pending'|'paused'};

/** Resolve uncertain writes with the retained reference before asking for correction. */
export async function submitWithRecovery<T extends Receipt>(
  attempt:Attempt,
  send:(attempt:Attempt)=>Promise<T>,
  lookup:(operation:string)=>Promise<T>,
  definitive:(error:unknown)=>boolean,
):Promise<T> {
  try {
    return await send(attempt);
  } catch (error) {
    if (definitive(error)) throw error;
    let result:T;
    try {
      result = await lookup(attempt.operation);
    } catch {
      // An absent receipt cannot establish whether the command was applied.
      throw error;
    }
    if (result.operation_id !== attempt.operation) throw new Error('Operation reference mismatch');
    return result;
  }
}
