export function useSession(){return null;}
export function useSessionState(){return 'signed-out' as const;}
export async function authenticatedRequest(){throw new Error('No authenticated transport in static presentation proof');}
export function signInHref(next:string,locale='en'){return `/${locale}/account?next=${encodeURIComponent(next)}`;}
