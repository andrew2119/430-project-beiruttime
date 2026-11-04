// Type-only consumer fixture from the frozen Identity browser contract. No runtime fallback.
import type { Session } from '@contracts/contracts-identity/accounts';
export declare function useSession():Session|null;
export declare function authenticatedRequest<T>(path:string,options?:RequestInit):Promise<T>;
export declare function signInHref(path:string,locale?:'en'|'ar'):string;
