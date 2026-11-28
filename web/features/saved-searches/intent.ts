import type { Draft } from './state';
// One short-lived public intent survives the shared provider's sign-in remount.
// It contains search fields only, never credentials or a private record reference.
let publicIntent:{draft:Draft;expires:number}|null=null;
export function holdPublicDraft(draft:Draft){publicIntent=draft.id===null?{draft:{...draft},expires:Date.now()+300000}:null;}
export function clearPublicDraft(){publicIntent=null;}
export function takePublicDraft(fingerprint:string|null):Draft|null {
  if(!fingerprint)return null;
  const held=publicIntent;publicIntent=null;
  return held&&held.expires>=Date.now()?{...held.draft}:null;
}
