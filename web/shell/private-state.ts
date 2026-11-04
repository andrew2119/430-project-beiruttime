'use client';
import type { Role } from '@/registry-types';
import { publishAccessContext } from './access-context';
// Only non-secret draft conveniences; no credentials, evidence or financial records.
let fingerprint: string | null = null;
const PREFIX = 'bt-draft:';
export function setAccessContext(next: string | null, roles: Role[] = ['public']) {
  let prior=fingerprint;
  try { prior ??= sessionStorage.getItem('bt-access-context'); } catch { /* Storage is optional; cache purge is not. */ }
  fingerprint=next;
  publishAccessContext({fingerprint:next,roles:next?roles:['public']});
  try {
    if(next) sessionStorage.setItem('bt-access-context',next); else sessionStorage.removeItem('bt-access-context');
    if(next!==prior) for(let i=sessionStorage.length-1;i>=0;i--) { const key=sessionStorage.key(i); if(key?.startsWith(PREFIX)) sessionStorage.removeItem(key); }
  } catch { /* Restricted storage must never prevent sign-out or query invalidation. */ }
  if(next!==prior) window.dispatchEvent(new Event('bt:access-change'));
}
export function saveNonSecretDraft(owner: string, key: string, value: string) {
  if(fingerprint!==owner || owner.length>200 || key.length>100 || value.length>32000) throw new Error('Draft scope or size refused');
  sessionStorage.setItem(`${PREFIX}${owner}:${key}`,value);
}
export function readNonSecretDraft(owner: string, key: string) {
  try { return fingerprint===owner ? sessionStorage.getItem(`${PREFIX}${owner}:${key}`) : null; } catch { return null; }
}
