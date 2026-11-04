import { beforeEach, describe, expect, it, vi } from 'vitest';
import { authenticatedRequest } from '@/features/identity/session';
import { mutation, operationsRequest } from '@/features/moderation/api';

vi.mock('@/features/identity/session',()=>({authenticatedRequest:vi.fn()}));
const transport=vi.mocked(authenticatedRequest);
beforeEach(()=>transport.mockReset());

describe('retired command scope',()=>{
  it('refuses a delayed private-file continuation before it acquires current credentials',async()=>{
    const lifetime=new AbortController();
    let finishRead!:(value:string)=>void;
    const reading=new Promise<string>(resolve=>{finishRead=resolve;});
    const upload=(async()=>{
      const content_base64=await reading;
      return operationsRequest('prior-fingerprint','service-operations','intake/records/old/evidence',mutation('POST','stable-key',{content_base64},1,lifetime.signal));
    })();
    lifetime.abort();
    finishRead('c2FtcGxl');
    await expect(upload).rejects.toMatchObject({status:401,code:'session_changed'});
    expect(transport).not.toHaveBeenCalled();
  });

  it('passes live cancellation and revision/idempotency to the shared coordinator',async()=>{
    const lifetime=new AbortController();
    transport.mockResolvedValue({revision:2});
    await expect(operationsRequest('fingerprint','trust','moderation/cases/sample/claim',mutation('POST','stable-key',undefined,1,lifetime.signal))).resolves.toEqual({revision:2});
    const [path,options]=transport.mock.calls[0];
    expect(path).toBe('/api/web/v1/trust/v1/moderation/cases/sample/claim');
    expect(options?.signal).toBe(lifetime.signal);
    expect(options?.accessFingerprint).toBe('fingerprint');
    const headers=new Headers(options?.headers);
    expect(headers.get('If-Match')).toBe('1');
    expect(headers.get('Idempotency-Key')).toBe('stable-key');
    expect(headers.has('Authorization')).toBe(false);
  });
});
