import { beforeEach, describe, expect, it, vi } from 'vitest';
const { send, authenticated, blob, refresh } = vi.hoisted(() => ({
  send: vi.fn(), authenticated: vi.fn(), blob: vi.fn(), refresh: vi.fn(),
}));
vi.mock('@/lib/api/client', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/lib/api/client')>(), request: send, requestBlob: blob,
}));
vi.mock('@/features/identity/session', () => ({ authenticatedRequest: authenticated, refreshSession: refresh }));
import { ApiError } from '@/lib/api/client';
import { optionsApi } from './api';
import en from './en.json';
import ar from './ar.json';

describe('brand options V1 transport', () => {
  beforeEach(() => {
    send.mockReset(); authenticated.mockReset(); blob.mockReset(); refresh.mockReset();
    send.mockResolvedValue({}); authenticated.mockResolvedValue({}); blob.mockResolvedValue(new Blob(['png']));
  });
  it('keeps locale namespaces symmetric', () => {
    expect(Object.keys(ar).sort()).toEqual(Object.keys(en).sort());
    expect(Object.values(ar).every(value => value.trim().length > 0)).toBe(true);
  });
  it('saves exact bindings through Identity with a stable caller operation key', async () => {
    const body = {brand_id:'brand',base_model:'atelier-38',caliber:'manual-01',option_id:'option',option_revision:3,expected_revision:7,component:'case' as const,reference_ids:[]};
    await optionsApi.save('configuration','material',body,'stable-operation');
    const [path,options] = authenticated.mock.calls[0];
    expect(path).toBe('/api/web/v1/catalog/v1/brand-options/configurations/configuration/material');
    expect(options.method).toBe('PUT'); expect(options.headers['Idempotency-Key']).toBe('stable-operation');
    expect(JSON.parse(options.body)).toEqual(body);
    expect(options.headers.Authorization).toBeUndefined();
    expect(send).not.toHaveBeenCalled();
  });
  it('cancels public and private canonical reads with the caller signal', async () => {
    const signal = new AbortController().signal;
    await optionsApi.brands(signal); await optionsApi.configuration('configuration',signal);
    expect(send.mock.calls[0][1].signal).toBe(signal);
    expect(authenticated.mock.calls[0][1].signal).toBe(signal);
  });
  it('passes the bounded directory cursor without turning it into a path', async () => {
    await optionsApi.brands(undefined,'next/cursor?');
    expect(send.mock.calls[0][0]).toBe('/api/web/v1/catalog/v1/brand-options/brands?after=next%2Fcursor%3F');
  });
  it('reads private images with the live memory-only credential, never a public file path', async () => {
    await optionsApi.reference('configuration','reference','current-token');
    expect(blob).toHaveBeenCalledWith('/api/web/v1/catalog/v1/brand-options/configurations/configuration/references/reference',{
      signal:undefined,headers:{Authorization:'Bearer current-token'},
    });
  });
  it('coordinates one image credential refresh after 401 and retries only once', async () => {
    blob.mockRejectedValueOnce(new ApiError(401,'unauthorized',''));
    refresh.mockResolvedValue({access_token:'renewed-token'});
    await optionsApi.reference('configuration','reference','expired-token');
    expect(refresh).toHaveBeenCalledTimes(1); expect(blob).toHaveBeenCalledTimes(2);
    expect(blob.mock.calls[1][1].headers.Authorization).toBe('Bearer renewed-token');
  });
  it('does not refresh on denied or unavailable private image reads', async () => {
    blob.mockRejectedValue(new ApiError(403,'forbidden',''));
    await expect(optionsApi.reference('configuration','reference','token')).rejects.toHaveProperty('status',403);
    expect(refresh).not.toHaveBeenCalled();
  });
  it('does not revive an image request after it was cancelled during refresh', async () => {
    const abort = new AbortController();
    blob.mockRejectedValueOnce(new ApiError(401,'unauthorized',''));
    refresh.mockImplementation(async () => {abort.abort();return {access_token:'renewed-token'};});
    await expect(optionsApi.reference('configuration','reference','token',abort.signal)).rejects.toHaveProperty('name','AbortError');
    expect(blob).toHaveBeenCalledTimes(1);
  });
  it('uploads PNG through the same authenticated transport without multipart or a public URL', async () => {
    const file = new File(['png'],'reference.png',{type:'image/png'});
    await optionsApi.upload('configuration',file,'upload-operation');
    const [path,options] = authenticated.mock.calls[0];
    expect(path).toBe('/api/web/v1/catalog/v1/brand-options/configurations/configuration/references');
    expect(options).toEqual({method:'POST',headers:{'Content-Type':'image/png','Idempotency-Key':'upload-operation'},body:file});
  });
});
