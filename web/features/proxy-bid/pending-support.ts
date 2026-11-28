'use client';

export type SupportAttempt=Readonly<{key:string;conversationId:string}>;
const listeners=new Set<()=>void>();
const prefix='bt.support-attempt.v1:';
const scope=(buyer:string,auction:string)=>`${prefix}${buyer}:${auction}`;
const uuid=(value:unknown):value is string=>typeof value==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value);

// Only the operation and conversation references survive a reload. The exact
// message body belongs to the private Communications attempt, not this store.
export function subscribePendingSupport(listener:()=>void) {
  listeners.add(listener);
  return ()=>{listeners.delete(listener);};
}
export const noPendingSupport=()=>null;
export function pendingSupport(buyer:string,auction:string):string|null|undefined {
  try {return sessionStorage.getItem(scope(buyer,auction));}
  catch {return undefined;}
}
export function parseSupportAttempt(value:string|null|undefined):SupportAttempt|null {
  if(!value) return null;
  const [key,conversationId,...extra]=value.split(':');
  return uuid(key)&&uuid(conversationId)&&!extra.length?{key,conversationId}:null;
}
export function retainSupportAttempt(buyer:string,auction:string,attempt:SupportAttempt) {
  if(!uuid(attempt.key)||!uuid(attempt.conversationId)||pendingSupport(buyer,auction)!==null) return false;
  const key=scope(buyer,auction),value=`${attempt.key}:${attempt.conversationId}`;
  try {
    sessionStorage.setItem(key,value);
    if(sessionStorage.getItem(key)!==value) return false;
  } catch {return false;}
  for(const listener of listeners) listener();
  return true;
}
export function settleSupportAttempt(buyer:string,auction:string,attempt:SupportAttempt) {
  try {
    if(pendingSupport(buyer,auction)!==`${attempt.key}:${attempt.conversationId}`) return;
    sessionStorage.removeItem(scope(buyer,auction));
  } catch {return;}
  for(const listener of listeners) listener();
}
