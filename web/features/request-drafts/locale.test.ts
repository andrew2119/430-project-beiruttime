import { afterEach, describe, expect, it, vi } from 'vitest';
import { changeRequestLocale } from './locale';

class LinkTarget {
  constructor(private href: string) {}
  closest() { return { href: this.href }; }
}
afterEach(() => vi.unstubAllGlobals());

function navigation(href = 'https://example.test/ar/custom-requests?draft=old') {
  let canonicalUrl = 'https://example.test/en/custom-requests?draft=current&filter=%D9%86%D8%B5#review';
  const refresh = vi.fn(() => canonicalUrl), fetch = vi.fn();
  const state = { retained: true, __NA: true, _N: true, __PRIVATE_NEXTJS_INTERNALS_TREE: { retained: 'tree' } };
  const replaceState = vi.fn((data, _unused, url) => {
    if (!data?.__NA && !data?._N) canonicalUrl = String(url);
  });
  vi.stubGlobal('Element', LinkTarget);
  vi.stubGlobal('window', { location: { href: 'https://example.test/en/custom-requests?draft=current&filter=%D9%86%D8%B5#review' }, history: { state, replaceState } });
  vi.stubGlobal('document', { cookie: '' });
  vi.stubGlobal('fetch', fetch);
  const event = { target: new LinkTarget(href), button: 0, preventDefault: vi.fn(), stopPropagation: vi.fn() };
  return { event: event as unknown as MouseEvent, refresh, replaceState, fetch, state };
}

describe('request language navigation', () => {
  it('refreshes presentation with the current exact query and no command or full navigation', () => {
    const n = navigation();
    changeRequestLocale(n.event, n.refresh);
    expect(n.event.preventDefault).toHaveBeenCalledOnce();
    expect(n.event.stopPropagation).toHaveBeenCalledOnce();
    const [state, , url] = n.replaceState.mock.calls[0];
    expect(state.retained).toBe(true);
    expect(state.__NA).toBeUndefined();
    expect(state._N).toBeUndefined();
    expect(state.__PRIVATE_NEXTJS_INTERNALS_TREE).toBe(n.state.__PRIVATE_NEXTJS_INTERNALS_TREE);
    expect(n.state.__NA).toBe(true);
    expect(String(url)).toBe('https://example.test/ar/custom-requests?draft=current&filter=%D9%86%D8%B5#review');
    expect(document.cookie).toContain('bt-locale=ar;');
    expect(n.refresh).toHaveBeenCalledOnce();
    expect(n.refresh.mock.results[0].value).toBe(String(url));
    expect(n.fetch).not.toHaveBeenCalled();
  });
  it.each(['https://example.test/ar/other', 'https://elsewhere.test/ar/custom-requests'])('ignores other destinations: %s', href => {
    const n = navigation(href);
    changeRequestLocale(n.event, n.refresh);
    expect(n.replaceState).not.toHaveBeenCalled();
    expect(n.refresh).not.toHaveBeenCalled();
  });
  it('keeps modified link gestures unchanged', () => {
    const n = navigation();
    changeRequestLocale({ ...n.event, ctrlKey: true }, n.refresh);
    expect(n.refresh).not.toHaveBeenCalled();
  });
});
