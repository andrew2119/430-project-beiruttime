/** The server and client share one cookie-backed, two-theme preference. */
export const THEMES = ['light', 'dark'] as const;
export type Theme = typeof THEMES[number];
export const THEME_COOKIE = 'bt-theme';
export const DEFAULT_THEME: Theme = 'light';
export function parseTheme(value: string | undefined | null): Theme { return value === 'dark' ? 'dark' : DEFAULT_THEME; }
export function nextTheme(theme: Theme): Theme { return theme === 'light' ? 'dark' : 'light'; }
export function themeCookieString(theme: Theme, secure: boolean): string {
  return [`${THEME_COOKIE}=${theme}`, 'Path=/', 'Max-Age=31536000', 'SameSite=Lax', ...(secure ? ['Secure'] : [])].join('; ');
}
