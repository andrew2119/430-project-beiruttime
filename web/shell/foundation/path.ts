import './page-registry';
import { stripLocale } from '@/shell/paths';

/** Locale prefixes never create a second frame or change its identity. */
export function shellPath(path: string): string {
  return stripLocale(path).split(/[?#]/)[0].replace(/\/$/, '') || '/';
}
/** The accepted component board already owns the canonical outlet and its room. */
export function pageOwnsToasts(path: string): boolean { return shellPath(path) === '/internal/components'; }

export function usesFoundationShell(path: string): boolean { void path; return true; }
export function shellForPath(serverPath: string, committedPath: string | null): 'foundation' {
  void serverPath; void committedPath; return 'foundation';
}
