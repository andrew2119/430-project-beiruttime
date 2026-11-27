import { describe, expect, it, vi } from 'vitest';
import { retainLocaleNavigation } from './locale';

describe('same-document locale recovery', () => {
  it('retains query, history state, inputs and pending identity without a command', () => {
    let handler: ((event: MouseEvent) => void) | undefined;
    const memory = { fields: { proof: 'مرجع Latin ⌚' }, operation: 'unchanged', step: 2 };
    const pending = memory;
    const anchor = { href: 'https://beirut-time.invalid/ar/seller/lifecycle' };
    class Target { closest() { return anchor; } }
    vi.stubGlobal('Element', Target);
    const doc = { cookie: '', addEventListener: vi.fn((_type, callback) => { handler = callback; }), removeEventListener: vi.fn() };
    const history = { state: { navigation: 'retained' }, replaceState: vi.fn() };
    const win = { location: { href: 'https://beirut-time.invalid/en/seller/lifecycle?filter=unsold#request' }, history };
    const refresh = vi.fn();
    const cleanup = retainLocaleNavigation(doc as unknown as Document, win as unknown as Window, refresh);
    const event = { target: new Target(), button: 0, preventDefault: vi.fn(), stopImmediatePropagation: vi.fn() };
    handler!(event as unknown as MouseEvent);
    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(event.stopImmediatePropagation).toHaveBeenCalledOnce();
    expect(refresh).toHaveBeenCalledOnce();
    expect(history.replaceState.mock.calls[0][0]).toBe(history.state);
    expect(String(history.replaceState.mock.calls[0][2])).toBe('https://beirut-time.invalid/ar/seller/lifecycle?filter=unsold#request');
    expect(memory).toBe(pending);
    expect(memory.fields.proof).toBe('مرجع Latin ⌚');
    expect(doc.cookie).toContain('bt-locale=ar');
    cleanup();
    expect(doc.removeEventListener).toHaveBeenCalledWith('click', handler, true);
    vi.unstubAllGlobals();
  });
  it('allows modified clicks without changing the page', () => {
    let handler: ((event: MouseEvent) => void) | undefined;
    class Target { closest() { return {href: 'https://beirut-time.invalid/ar/seller/lifecycle'}; } }
    vi.stubGlobal('Element', Target);
    const doc = { addEventListener: vi.fn((_type, callback) => { handler = callback; }), removeEventListener: vi.fn() };
    const refresh = vi.fn();
    retainLocaleNavigation(doc as unknown as Document, {} as Window, refresh);
    const event = { target: new Target(), button: 0, ctrlKey: true, preventDefault: vi.fn() };
    handler!(event as unknown as MouseEvent);
    expect(refresh).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
