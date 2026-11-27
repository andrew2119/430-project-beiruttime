type SessionFixture={access_fingerprint:string;principal:{actor:{subject_id:string};permissions:string[];organization_grants:[]}};
let current:SessionFixture|null=null;
export function setSessionFixture(value:SessionFixture|null){current=value;}
export function useSession(){return current;}
export function useSessionState(){return 'signed-out' as const;}
export async function authenticatedRequest(){throw new Error('No authenticated transport in static presentation proof');}
export function signInHref(next:string,locale='en'){return `/${locale}/account?next=${encodeURIComponent(next)}`;}
