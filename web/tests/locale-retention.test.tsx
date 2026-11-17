import { afterEach, expect, it, vi } from 'vitest';
import { type ReactElement } from 'react';
import { readFileSync } from 'node:fs';
import { LocaleProvider } from '../shell/locale-context';

const state = vi.hoisted(() => ({ locale: 'en', refresh: vi.fn(), effects: [] as (() => (() => void))[] }));
vi.mock('react', async () => ({ ...await vi.importActual('react'), useEffect: (effect: () => (() => void)) => { state.effects.push(effect); }, useState: () => [state.locale, (next: string) => { state.locale = next; }] }));
vi.mock('next/navigation', () => ({useRouter: () => ({refresh: state.refresh})}));
afterEach(() => { state.locale = 'en'; state.effects = []; vi.resetAllMocks(); vi.unstubAllGlobals(); });

it('changes only locale metadata and retains the exact child subtree and history state', () => {
  let href = 'https://example.test/en/settings?q=%D8%B3%D8%A7%D8%B9%D8%A9&step=2#language';
  const historyState = { retained: 'current-route', __NA: true, _N: true };
  let canonical = href;
  const refreshed: string[] = [];
  state.refresh.mockImplementation(() => {refreshed.push(canonical);});
  const replaceState = vi.fn((data: {__NA?:boolean;_N?:boolean}, _unused, url: URL) => {
    // Internal history markers bypass the route's external-URL synchronization.
    if (!data.__NA && !data._N) canonical = url.href;
    expect(document.cookie).toContain(`bt-locale=${url.pathname.split('/')[1]};`);
    href = url.href;
  });
  const root = { lang: 'en', dir: 'ltr' };
  const document = { documentElement: root, cookie: '' };
  vi.stubGlobal('document', document);
  const listeners = new Map<string, () => void>();
  vi.stubGlobal('window', { addEventListener: (name: string, run: () => void) => listeners.set(name, run), removeEventListener: (name: string) => listeners.delete(name), location: { get href() { return href; } }, history: { state: historyState, replaceState } });
  // These references stay with the page. The provider never reads or serializes them.
  const pending = { operation_id: 'operation-17', state: 'pending' };
  const children = <form data-operation={pending.operation_id}><input type="password" defaultValue="test-unsent-password"/><input type="file"/><input defaultValue="نور ⌚"/></form>;
  const draw = () => LocaleProvider({ locale: 'en', children });
  const change = (view: ReturnType<typeof draw>, locale: string) => {
    const context = view.props.children as ReactElement<{ value: (locale: string) => void }>;
    context.props.value(locale);
  };
  for (const locale of ['ar', 'en']) {
    change(draw(), locale);
    const view = draw();
    expect(view.props.value).toBe(locale);
    expect(view.props.children.props.children).toBe(children);
    expect(root).toEqual({ lang: locale, dir: locale === 'ar' ? 'rtl' : 'ltr' });
    expect(new URL(href).search).toBe('?q=%D8%B3%D8%A7%D8%B9%D8%A9&step=2');
    expect(new URL(href).hash).toBe('#language');
    expect(new URL(href).pathname).toBe(`/${locale}/settings`);
    expect(replaceState.mock.lastCall?.[0]).toEqual({retained:'current-route'});
    expect(historyState).toEqual({retained:'current-route',__NA:true,_N:true});
    expect(refreshed.at(-1)).toBe(href);
    expect(document.cookie).toBe(`bt-locale=${locale}; Path=/; Max-Age=31536000; SameSite=Lax`);
    expect(pending).toEqual({ operation_id: 'operation-17', state: 'pending' });
  }
  expect(state.refresh).toHaveBeenCalledTimes(2);
  change(draw(), 'en');
  expect(state.refresh).toHaveBeenCalledTimes(2);
  expect(replaceState).toHaveBeenCalledTimes(2);
  const cleanups = state.effects.slice(-2).map(effect => effect());
  href = 'https://example.test/ar/account?return=1';
  listeners.get('popstate')!();
  expect(draw().props.value).toBe('ar');
  expect(root).toEqual({ lang: 'ar', dir: 'rtl' });
  expect(replaceState).toHaveBeenCalledTimes(2);
  cleanups.forEach(cleanup => cleanup()); expect(listeners.size).toBe(0);
});

it('both controls use the shared in-place change without document navigation or private persistence', () => {
  const read = (file: string) => readFileSync(new URL(file, import.meta.url), 'utf8');
  for (const file of ['../shell/settings.tsx', '../shell/foundation/locale-control.tsx']) {
    const source = read(file);
    expect(source).toContain('useLocaleChange');
    expect(source).toContain('changeLocale(');
    expect(source).not.toMatch(/location\.(assign|replace)|before-locale-change/);
  }
  expect(read('../shell/foundation/locale-control.tsx')).toContain('<Button ');
  expect(read('../shell/foundation/locale-control.tsx')).not.toContain('<a ');
  expect(read('../shell/locale-context.tsx')).not.toMatch(/localStorage|sessionStorage|indexedDB|querySelector|FormData/);
});
