import { describe, expect, it } from '../../../../web/node_modules/vitest';
import { PhotoAction } from '../../../../web/features/message-photos/action';
import { copy } from '../../../../web/features/message-photos/copy';
import type { MessagePhotos, PhotoResult } from '../../../../packages/contracts-comms/message-photos';

const receipt = (operation_id: string, state: PhotoResult['state'], photo?: string): PhotoResult => ({
  schema_version: 'communications.message-photos.v1', operation_id, subject_id: 'thread',
  watch_id: 'watch', actor_id: 'buyer', organization_id: 'business', expected_revision: 1,
  revision: 1, state, pending_reason: state === 'pending' ? 'result_unknown' : null,
  next_actor: state === 'pending' ? 'buyer' : null, next_review_at: null, ...(photo ? { photo } : {}),
});
const providerDouble = (overrides: Partial<MessagePhotos>): MessagePhotos => ({
  upload: async (_file, operation) => receipt(operation, 'uploaded', 'photo'),
  attach: async (photo, operation) => receipt(operation, 'attached', photo),
  operation: async operation => receipt(operation, 'pending'),
  list: async () => ({ items: [], total: 0, next_offset: null }),
  bytes: async () => new Blob(),
  ...overrides,
});

describe('private photo draft', () => {
  it('retains the exact file and both references after an uncertain response', async () => {
    let sequence = 0, lost = true;
    const draft = new PhotoAction(() => `operation-${++sequence}`);
    const file = { name: 'تفصيل-detail-⌚.jpg', size: 100 } as File;
    const calls: unknown[][] = [];
    const provider = providerDouble({
      upload: async (bytes: File, reference: string) => {
        calls.push([bytes, reference]);
        if (lost) { lost = false; throw new Error('timeout'); }
        return receipt(reference, 'uploaded', 'private-photo');
      },
      attach: async (photo: string, reference: string) => {
        calls.push([photo, reference]);
        return receipt(reference, 'attached', photo);
      },
    });
    const signal = new AbortController().signal;
    await expect(draft.run(provider, file, signal)).rejects.toThrow('timeout');
    expect(copy.en.title).not.toBe(copy.ar.title);
    expect(calls).toHaveLength(1);
    expect(await draft.run(provider, file, signal)).toEqual(receipt('operation-2', 'attached', 'private-photo'));
    expect(calls).toEqual([[file, 'operation-1'], [file, 'operation-1'], ['private-photo', 'operation-2']]);
    expect(sequence).toBe(2);
  });
  it('never attaches a pending or aborted upload', async () => {
    const draft = new PhotoAction(() => 'stable');
    let attached = false;
    const provider = providerDouble({ upload: async () => receipt('stable', 'pending'), attach: async () => { attached = true; return receipt('stable', 'attached'); } });
    expect((await draft.run(provider, {} as File, new AbortController().signal)).state).toBe('pending');
    expect(attached).toBe(false);
  });
  it('supplies every recovery label in both languages', () => {
    expect(Object.keys(copy.ar).sort()).toEqual(Object.keys(copy.en).sort());
    for (const label of Object.values(copy.ar)) expect(label).toMatch(/[\u0600-\u06ff]/);
  });
});

it('retries an uncertain attachment without uploading again', async () => {
  const draft = new PhotoAction(() => 'stable');
  let uploads = 0, attachments = 0;
  const provider = providerDouble({
    upload: async () => { uploads++; return receipt('stable', 'uploaded', 'photo'); },
    attach: async () => { if (++attachments === 1) throw new Error('lost-response'); return receipt('stable', 'attached'); },
  });
  const signal = new AbortController().signal;
  await expect(draft.run(provider, {} as File, signal)).rejects.toThrow('lost-response');
  expect((await draft.run(provider, {} as File, signal)).state).toBe('attached');
  expect(uploads).toBe(1);
  expect(attachments).toBe(2);
});

import { photoProvider, type PhotoTransport } from '../../../../web/features/message-photos/adapter';
it('binds protected requests to the current conversation and disables caching', async () => {
  const calls: { path: string; options: RequestInit; format: string }[] = [];
  const transport = (async (path: string, options: RequestInit, format: string) => {
    calls.push({ path, options, format }); return {};
  }) as PhotoTransport;
  const provider = photoProvider({ actor: 'buyer', business: 'business', thread: 'thread/⌚', watch: 'watch', revision: 7 }, transport);
  const signal = new AbortController().signal;
  await provider.upload({} as File, 'upload-1', signal);
  await provider.attach('private/photo', 'attach-1', signal);
  await provider.bytes('private/photo', signal);
  expect(calls).toHaveLength(3);
  for (const call of calls) {
    expect(call.options.cache).toBe('no-store');
    expect(call.options.signal).toBe(signal);
    const url = new URL(call.path, 'https://beirut-time.invalid');
    expect(url.searchParams.get('thread')).toBe('thread/⌚');
    expect(url.searchParams.get('expected_revision')).toBe('7');
  }
  expect(calls[2].path).toContain('/private%2Fphoto/bytes');
  expect(calls[2].format).toBe('blob');
});

it('stops waiting on timeout and retries with the original reference', async () => {
  const draft = new PhotoAction(() => 'stable');
  const controller = new AbortController();
  let calls = 0;
  const provider = providerDouble({
    upload: async () => { calls++; return new Promise(() => {}); },
  });
  const result = draft.run(provider, {} as File, controller.signal);
  controller.abort(new Error('timeout'));
  await expect(result).rejects.toThrow('timeout');
  expect(draft.upload).toBe('stable');
  await expect(draft.run(provider, {} as File, controller.signal)).rejects.toThrow('timeout');
  expect(calls).toBe(1);
});

import { readFailure, recoveredRead } from '../../../../web/features/message-photos/recovery';
it('keeps temporary read failures recoverable and clears their state after recovery', () => {
  for (const error of [new Error('timeout'), { code: 'unavailable' }, undefined]) {
    expect(readFailure(error)).toBe('unavailable');
    expect(recoveredRead(readFailure(error))).toBe('empty');
  }
  for (const code of ['denied', 'unauthorized']) expect(readFailure({ code })).toBe('denied');
  expect(recoveredRead('pending')).toBe('pending');
  expect(recoveredRead('attached')).toBe('attached');
});
