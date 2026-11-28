import { describe, expect, it, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { COPY } from '../../../../web/features/two-factor/copy';
const { invoke } = vi.hoisted(()=>({invoke: vi.fn()}));
vi.mock('@/features/identity/session', ()=>({authenticatedRequest: invoke}));
import { statusRead, submitFactor, type FactorCommand } from '../../../../web/features/two-factor/transport';

const command: FactorCommand = {schema_version: 1, operation_id: 'operation-private-1', expected_revision: 2, kind: 'confirm', proof: '123456'};
beforeEach(()=>invoke.mockReset());
describe('private form contract', ()=>{
  it('has complete matching language states', ()=>{
    expect(Object.keys(COPY.en).sort()).toEqual(Object.keys(COPY.ar).sort());
    for (const locale of [COPY.en, COPY.ar]) for (const text of Object.values(locale)) expect(text.length).toBeGreaterThan(0);
  });
  it('retains the exact operation and secret in memory across retry', async()=>{
    invoke.mockRejectedValueOnce(new Error('timeout')).mockResolvedValueOnce({schema_version: 1, operation_id: command.operation_id, revision: 3, state: 'enabled', recovery_codes: Array.from({length:10}, (_, n)=>String(n).padStart(32, '0'))});
    await expect(submitFactor(command, 'scope-one')).rejects.toThrow();
    await expect(submitFactor(command, 'scope-one')).resolves.toMatchObject({state: 'enabled'});
    expect(invoke.mock.calls[0]).toEqual(invoke.mock.calls[1]);
    expect(JSON.parse(invoke.mock.calls[0][1].body)).toEqual(command);
  });
  it('refuses a mismatched operation or revision', async()=>{
    invoke.mockResolvedValueOnce({schema_version: 1, operation_id: 'other', revision: 3, state: 'enabled'});
    await expect(submitFactor(command, 'scope-one')).rejects.toThrow('unavailable');
    invoke.mockResolvedValueOnce({schema_version: 1, operation_id: command.operation_id, revision: 2, state: 'enabled'});
    await expect(submitFactor(command, 'scope-one')).rejects.toThrow('unavailable');
  });
  it('uses open-only access-partitioned status reads', async()=>{
    const read = statusRead('scope-one');
    expect(read.key).toEqual(['two-factor-status-v1', 'scope-one']);
    expect(read.warm).toBe('open-only');
    invoke.mockResolvedValueOnce({schema_version: 1, revision: 2, state: 'enabled'});
    await read.ask(new AbortController().signal);
    expect(invoke.mock.calls[0][1].accessFingerprint).toBe('scope-one');
  });
  it('keeps locale out of form identity and never writes private browser storage', ()=>{
    const source = readFileSync(new URL('../../../../web/features/two-factor/view.tsx', import.meta.url), 'utf8');
    expect(source).toContain('key={session.access_fingerprint}');
    expect(source).not.toMatch(/key=\{locale\}|localStorage|sessionStorage|document\.cookie/);
    expect(source).toContain('pending ??');
  });
});
