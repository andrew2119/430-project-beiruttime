import { describe, expect, it } from 'vitest';
import type { Command, Visit } from '@contracts/contracts-service/appointments';
import { VisitCommand } from './command';
import { visitTime } from './time';
import en from './en.json';
import ar from './ar.json';

const command:Command = {schema_version:'appointments.v1',operation_id:'operation-1',appointment_id:'visit-1',
  subject_id:'buyer-1',watch_id:'watch-1',actor_id:'buyer-1',organization_id:'business-1',expected_revision:0,
  source_revision:2,policy_revision:3,assignment_revision:4,quote_id:null,quote_revision:null,kind:'request',
  purpose:'fit',civil_time:'2027-01-10T10:00',timezone:'Asia/Beirut',selected_instant:null,
  repeated_time_confirmed:false,duration_minutes:30};
const visit:Visit = {...command,instant:'2027-01-10T08:00:00Z',revision:1,state:'requested',confirmed_by:null,
  pending_reason:'business_confirmation',next_actor:'business',next_review_at:'2027-01-02T00:00:00Z',
  custody_received:false,work_authorized:false,physical_release_allowed:false};

describe('private visit references',()=>{
  it('retains exact choices, bindings and reference while the visible language changes',()=>{
    const state = new VisitCommand();
    const saved = state.begin(command);
    for (const language of [ar,en,ar]) {
      expect(language.pending).toBeTruthy();
      expect(state.pending).toBe(saved);
      expect(state.pending?.civil_time).toBe('2027-01-10T10:00');
      expect(state.pending?.source_revision).toBe(2);
    }
    expect(Object.isFrozen(saved)).toBe(true);
    expect(state.begin({...command,operation_id:'different',purpose:'assessment'})).toBe(saved);
  });
  it('only acknowledges the bound operation and preserves uncertain requests',()=>{
    const state = new VisitCommand();state.begin(command);
    expect(()=>state.acknowledge({...visit,operation_id:'different'})).toThrow('operation_mismatch');
    expect(state.pending).toEqual(command);
    state.acknowledge(visit);
    expect(state.pending).toBeNull();expect(state.result).toEqual(visit);
    expect(state.result?.physical_release_allowed).toBe(false);
  });
  it('clears retained private answers on access change',()=>{
    const state = new VisitCommand();state.begin(command);state.acknowledge(visit);state.begin(command);
    state.clear();expect(state.pending).toBeNull();expect(state.result).toBeNull();
  });
  it('provides matching complete recovery dictionaries',()=>{
    expect(Object.keys(ar).sort()).toEqual(Object.keys(en).sort());
    for (const value of [...Object.values(en),...Object.values(ar)]) expect(value.trim()).not.toBe('');
  });
});

it('formats retained instants with explicit Beirut time and reader digit shapes',()=>{
  expect(visitTime('2027-01-10T08:00:00Z','en')).toContain('10:00');
  expect(visitTime('2027-01-10T08:00:00Z','ar')).toContain('١٠:٠٠');
  expect(visitTime('invalid','ar')).toBe('—');
});
