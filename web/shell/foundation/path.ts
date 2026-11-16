import { stripLocale } from '@/shell/paths';

/** Only the reviewed internal area adopts the new composition during migration. */
export function shellPath(path: string): string {
  return stripLocale(path).split(/[?#]/)[0].replace(/\/$/, '') || '/';
}
export function usesFoundationShell(path: string): boolean {
  const plain = shellPath(path);
  return plain === '/internal' || plain.startsWith('/internal/');
}
export function shellForPath(serverPath: string, committedPath: string | null): 'foundation' | 'legacy' {
  return usesFoundationShell(committedPath ?? serverPath) ? 'foundation' : 'legacy';
}
/** The accepted component board already owns the canonical outlet and its room. */
export function pageOwnsToasts(path: string): boolean { return shellPath(path) === '/internal/components'; }
