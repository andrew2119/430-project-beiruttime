import { beforeEach, describe, expect, it, vi } from 'vitest';
import { setAccessContext } from '@/shell/private-state';
import { currencyChoice, intakeSelection, organizationChoice, reportChoices, saveCurrencyChoice, saveIntakeSelection, saveOrganizationChoice, saveReportChoices } from '@/features/moderation/drafts';

class MemoryStorage {
  values=new Map<string,string>();
  get length(){return this.values.size;}
  key(index:number){return [...this.values.keys()][index]??null;}
  getItem(key:string){return this.values.get(key)??null;}
  setItem(key:string,value:string){this.values.set(key,value);}
  removeItem(key:string){this.values.delete(key);}
}
const id='10000000-0000-4000-8000-000000000001';
const org='10000000-0000-4000-8000-000000000002';
let storage:MemoryStorage;
beforeEach(()=>{
  storage=new MemoryStorage();vi.stubGlobal('sessionStorage',storage);vi.stubGlobal('window',new EventTarget());
  setAccessContext(null);setAccessContext('scope-a',['buyer']);
});

describe('same-account non-secret locale conveniences',()=>{
  it('retains only public listing references and choices, never private evidence',()=>{
    const form={target_kind:'listing',target_id:id,category:'misleading',evidence:'PRIVATE EVIDENCE MUST NOT PERSIST',serial:'PRIVATE SERIAL'};
    saveReportChoices('scope-a',form);
    expect(reportChoices('scope-a')).toEqual({target_kind:'listing',target_id:id,category:'misleading'});
    const persisted=[...storage.values.values()].join();
    expect(persisted).not.toContain('PRIVATE');expect(persisted).not.toContain('evidence');expect(persisted).not.toContain('serial');
    saveReportChoices('scope-a',{...form,target_kind:'message'});
    expect(reportChoices('scope-a').target_id).toBe('');
    expect([...storage.values.values()].join()).not.toContain(id);
  });
  it('validates business/record selections and keeps only a currency preference',()=>{
    saveOrganizationChoice('scope-a',org);saveIntakeSelection('scope-a',org,id);saveCurrencyChoice('scope-a','LBP');
    expect(organizationChoice('scope-a',[org])).toBe(org);
    expect(organizationChoice('scope-a',[])).toBe('');
    expect(intakeSelection('scope-a',org)).toBe(id);
    expect(currencyChoice('scope-a')).toBe('LBP');
    expect([...storage.values.values()].join()).not.toContain('fee_minor');
  });
  it('purges prior-user choices and fences a late prior-user writer',()=>{
    saveReportChoices('scope-a',{target_kind:'listing',target_id:id,category:'other'});
    setAccessContext('scope-b',['buyer']);
    saveReportChoices('scope-a',{target_kind:'listing',target_id:id,category:'other'});
    expect([...storage.values.keys()].filter(key=>key.startsWith('bt-draft:'))).toEqual([]);
    expect(reportChoices('scope-a').target_id).toBe('');
    expect(reportChoices('scope-b').target_id).toBe('');
  });
  it('ignores tampered private fields, malformed storage and storage refusal',()=>{
    storage.setItem('bt-draft:scope-a:moderation-choices',JSON.stringify({target_kind:'invalid',target_id:'private',category:'invalid',evidence:'PRIVATE'}));
    expect(reportChoices('scope-a')).toEqual({target_kind:'listing',target_id:'',category:'misleading'});
    storage.setItem('bt-draft:scope-a:moderation-choices','not json');
    expect(reportChoices('scope-a').target_id).toBe('');
    vi.spyOn(storage,'setItem').mockImplementation(()=>{throw new Error('Storage refused');});
    expect(()=>saveCurrencyChoice('scope-a','USD')).not.toThrow();
  });
});
