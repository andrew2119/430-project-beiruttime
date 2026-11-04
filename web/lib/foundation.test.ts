import { afterEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { direction, messages, normalizeDigits } from './i18n';
import { navigation, validateRegistrations } from '../registry-loader';
import { pathMatches } from '../gateway/forward';
import { Dependency } from './bff/dependency';
import { request, requestBlob, ApiError } from './api/client';

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('bilingual contracts', () => {
  it('keeps domain translation keys in parity', () => {
    const root = resolve('../packages/i18n/messages');
    const en = JSON.parse(readFileSync(`${root}/en.json`, 'utf8'));
    const ar = JSON.parse(readFileSync(`${root}/ar.json`, 'utf8'));
    expect(Object.keys(ar).sort()).toEqual(Object.keys(en).sort());
    expect(Object.values(ar).every(v => typeof v === 'string' && v.length > 0)).toBe(true);
    expect(direction('ar')).toBe('rtl');
    expect(messages('ar').brand).toBe('بيروت تايم');
    expect(normalizeDigits('١٢٫٥۰')).toBe('12.50');
    expect(() => validateRegistrations([{lane:'L00',namespace:'../escape',routes:[],dictionaries:{en:{},ar:{}}}])).toThrow();
    expect(pathMatches('/v1/listings/:id',['v1','listings','demo-1'])).toBe(true);
    expect(pathMatches('/v1/listings/:id',['v1','listings','..'])).toBe(false);
  });
  it('has unique file-contributed navigation', () => {
    expect(new Set(navigation.map(n => n.id)).size).toBe(navigation.length);
    expect(navigation.every(n => n.label.en && n.label.ar)).toBe(true);
  });
});

describe('transport isolation', () => {
  it('opens a per-dependency circuit and retains healthy responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 503 })));
    const dependency = new Dependency('catalog', 'http://catalog');
    for (let i = 0; i < 3; i++) expect(await dependency.get('/health/ready','test')).toHaveProperty('kind','unavailable');
    expect(await dependency.get('/health/ready','test')).toHaveProperty('kind','unavailable');
    expect(fetch).toHaveBeenCalledTimes(3);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 200 })));
    expect(await new Dependency('orders','http://orders').get('/health/ready','test')).toBeInstanceOf(Response);
  });
  it('sheds excess calls without queueing and releases the budget', async () => {
    let release!: (r: Response) => void;
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise<Response>(r => { release = r; })));
    const dependency = new Dependency('slow', 'http://slow', 100, 1);
    const first = dependency.get('/health/ready','test');
    expect(await dependency.get('/health/ready','test')).toHaveProperty('kind','unavailable');
    release(new Response(null, { status: 200 }));
    await first;
    expect(dependency.active).toBe(0);
  });
  it('shares the bounded transport for private binary reads', async () => {
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('synthetic-private-proof',{headers:{'Content-Type':'application/octet-stream'}})));
    const blob=await requestBlob('/api/web/v1/identity/v1/files/proof');
    expect(await blob.text()).toBe('synthetic-private-proof');
    await expect(requestBlob('https://example.invalid/private')).rejects.toMatchObject({code:'invalid_api_path'});
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith(expect.any(String),expect.objectContaining({cache:'no-store',credentials:'same-origin',signal:expect.any(AbortSignal)}));
  });
  it('retains server support references in a typed error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ error: { code:'forbidden',request_id:'proof-123',details:{field:'name'} } },{status:403})));
    await expect(request('/api/web/v1/denied')).rejects.toEqual(new ApiError(403,'forbidden','proof-123',{field:'name'}));
  });
});
