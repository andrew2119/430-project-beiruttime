// Contract-only test double. Production imports the owning Identity provider, never this file.
export type Session = { access_fingerprint:string;principal:{roles:string[];permissions:string[];actor:{subject_id:string;organization_id:string|null};organization_grants:{organization_id:string;permissions:string[];roles:string[]}[]};access_token:string };
export function useSession():Session|null { return null; }
export type AuthenticatedRequestInit=RequestInit&{accessFingerprint?:string};
export function useSessionState():'restoring'|'signed-out'|'unavailable'|'authenticated' {return 'signed-out';}
export async function refreshSession():Promise<Session|null> {return null;}
export async function authenticatedRequest<T>(_path:string,_options?:AuthenticatedRequestInit):Promise<T> { throw new Error('Configure the request fixture'); }
export function signInHref(next:string,locale:'en'|'ar'='en') { return `/${locale}/account?next=${encodeURIComponent(next)}`; }
