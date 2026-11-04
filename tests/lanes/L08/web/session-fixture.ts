// Explicit test-only transport. Never imported by a production registration or feature.
export function useSession(){return null;}
export function signInHref(path:string,locale:string){return `/${locale}/account?next=${encodeURIComponent(path)}`;}
export async function authenticatedRequest():Promise<never>{throw new Error('Unexpected authenticated request in signed-out rendering proof');}
