import { beforeEach, describe, expect, it, vi } from 'vitest';
const { request } = vi.hoisted(() => ({request:vi.fn()}));
vi.mock('./transport', () => ({businessRequest:request}));
import { ApiError } from '@/lib/api/client';
import { knownRejection } from './command-form';
import { BusinessOperation } from './operation-v2';
const body = {actor_id:'actor',subject_id:'colleague',organization_id:'business',expected_revision:3};
const response = (operation:BusinessOperation) => ({operation_id:operation.id,operation_state:'committed',state:'active',revision:4});
beforeEach(() => request.mockReset());
describe('business operation recovery', () => {
  it('retries the exact reference and request after a lost response', async () => {
    const operation = new BusinessOperation();
    request.mockRejectedValueOnce(new TypeError('Response unavailable')).mockResolvedValue(response(operation));
    await expect(operation.send('/v2/business-staff/commands',body)).rejects.toThrow();
    await expect(operation.retry()).resolves.toEqual(response(operation));
    expect(request.mock.calls[1]).toEqual(request.mock.calls[0]);
    expect(JSON.parse(request.mock.calls[0][1].body)).toMatchObject({operation_id:operation.id,expected_revision:3});
  });
  it('rejects changed business, subject, revision and reordered commands under one reference', async () => {
    const operation = new BusinessOperation(); request.mockResolvedValue(response(operation));
    await operation.send('/command',body);
    for (const change of [{organization_id:'other'}, {subject_id:'other'}, {expected_revision:4}]) {
      await expect(operation.send('/command',{...body,...change})).rejects.toThrow('operation_conflict');
    }
    await expect(operation.send('/other',body)).rejects.toThrow('operation_conflict');
    expect(request).toHaveBeenCalledTimes(1);
  });
  it('recovers by lookup without issuing a new command', async () => {
    const operation = new BusinessOperation();request.mockResolvedValue(response(operation));
    await operation.recover();
    expect(request).toHaveBeenCalledWith(`/v2/business-operations/${operation.id}`);
  });
  it('never converts denied, stale or timed-out reads into success', async () => {
    const operation = new BusinessOperation();
    for (const error of ['denied','stale_revision','timeout']) {
      request.mockRejectedValueOnce(new Error(error));
      await expect(operation.recover()).rejects.toThrow(error);
    }
  });
  it('discards a late reply after access changes', async () => {
    let finish!: (value:unknown) => void;
    request.mockReturnValue(new Promise(resolve => {finish=resolve;}));
    const operation = new BusinessOperation(), pending = operation.send('/command',body);
    operation.dispose(); finish(response(operation));
    await expect(pending).rejects.toThrow('access_changed');
    await expect(operation.send('/command',body)).rejects.toThrow('access_changed');
  });
  it('retains the same private upload on retry and excludes bytes from the command', async () => {
    const operation = new BusinessOperation(), file = new File(['private'],'photo.png',{type:'image/png'});
    request.mockRejectedValueOnce(new Error('timeout')).mockResolvedValue({evidence_ref:'private-reference'});
    const binding={watch_id:'watch',listing_revision:'1',challenge_id:'challenge'};
    await expect(operation.photo(file,binding)).rejects.toThrow('timeout');
    expect(await operation.photo(file,binding)).toBe('private-reference');
    expect(request.mock.calls[0][1].headers).toEqual(request.mock.calls[1][1].headers);
    expect(request.mock.calls[1][1].body.get('photo')).toBe(file);
    expect(await operation.photo(file,binding)).toBe('private-reference');
    expect(request).toHaveBeenCalledTimes(2);
    await expect(operation.photo(file,{...binding,watch_id:'other'})).rejects.toThrow('operation_conflict');
  });
});

it.each([400,403,409,413,415,422])('permits corrected inputs after definitive rejection %i',status=>{
  expect(knownRejection(new ApiError(status,'rejected',''))).toBe(true);
});
it.each([404,429,503])('retains the original reference after uncertain response %i',status=>{
  expect(knownRejection(new ApiError(status,'unavailable',''))).toBe(false);
});
it('distinguishes committed review-pending from an unresolved operation',async()=>{
  const operation=new BusinessOperation();
  request.mockResolvedValue({...response(operation),state:'pending'});
  await expect(operation.send('/command',body)).resolves.toMatchObject({operation_state:'committed',state:'pending'});
  request.mockResolvedValue({...response(operation),operation_state:'pending',state:'pending'});
  await expect(operation.recover()).resolves.toMatchObject({operation_state:'pending'});
});

it('freezes platform membership edits and recovers by identical replay', async () => {
  const operation = new BusinessOperation();
  const edit = {revision:3,state:'suspended',reason:'Current responsibility review'};
  request.mockRejectedValueOnce(new TypeError('Response unavailable')).mockResolvedValue({revision:4,state:'suspended'});
  await expect(operation.membership('/v1/memberships/member',edit,'PATCH')).rejects.toThrow();
  await expect(operation.membership('/v1/memberships/member',{...edit,state:'active'},'PATCH')).rejects.toThrow('operation_conflict');
  await expect(operation.recover()).resolves.toMatchObject({operation_id:operation.id,operation_state:'committed',revision:4});
  expect(request.mock.calls[1]).toEqual(request.mock.calls[0]);
  expect(request).toHaveBeenCalledTimes(2);
});

it('replays a retained submission after interrupted upload and absent lookup', async () => {
  const operation = new BusinessOperation();
  const file = new File(['test-private-photo'], 'photo.png', {type:'image/png'});
  const binding = {watch_id:'test-watch',listing_revision:'1',challenge_id:'test-challenge'};
  operation.retainSubmission(async () => {
    const evidence_ref = await operation.photo(file, binding);
    return operation.send('/v2/listing-possession/submissions', {...body,evidence_ref});
  });
  request.mockRejectedValueOnce(new TypeError('Response unavailable'));
  await expect(operation.replay()).rejects.toThrow();
  const upload = request.mock.calls[0];
  request.mockRejectedValueOnce(new ApiError(404,'missing',''));
  await expect(operation.recover()).rejects.toMatchObject({status:404});
  request.mockResolvedValueOnce({evidence_ref:'test-private-reference'}).mockResolvedValueOnce(response(operation));
  await expect(operation.replay()).resolves.toEqual(response(operation));
  expect(request.mock.calls[2][1].headers).toEqual(upload[1].headers);
  expect(request.mock.calls[2][1].body.get('photo')).toBe(file);
  expect(JSON.parse(request.mock.calls[3][1].body)).toMatchObject({operation_id:operation.id,evidence_ref:'test-private-reference'});
  operation.dispose();
  await expect(operation.replay()).rejects.toThrow('access_changed');
});
