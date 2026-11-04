declare module '@/features/identity/session' {
  type Session = import('./accounts').Session;
  export function useSession(): Session | null;
  export function authenticatedRequest<T>(path:string,options?:RequestInit):Promise<T>;
  export function refreshSession():Promise<Session|null>;
  export function signOut():Promise<void>;
  export function signInHref(next:string,locale:'en'|'ar'):string;
}
