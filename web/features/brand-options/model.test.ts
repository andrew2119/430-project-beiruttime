import { describe, expect, it } from 'vitest';
import type { Configuration, SelectionWrite } from '@contracts/contracts-catalog/options';
import { matchesAcknowledgedSelection } from './model';
const body: SelectionWrite = {brand_id:'brand',base_model:'base',caliber:'caliber',component:'dial',option_id:'option',option_revision:3,expected_revision:7,reference_ids:['a','b']};
const configuration = (): Configuration => ({
  id:'config',brand_id:'brand',base_model:'base',caliber:'caliber',revision:8,state:'saved_not_submitted',feasibility:'not_assessed',reference_ids:['a','b'],updated_at:'2026-11-04T06:00:00Z',
  selections:[{kind:'dial',component:'dial',option_id:'option',option_revision:3,reference_ids:['b','a'],current:true,
    definition:{component:'dial',label:{en:'Sample dial',ar:'ميناء نموذجي'},base_models:['base'],calibers:['caliber'],available:true,
      details:{dial:{en:'Sample',ar:'نموذج'},hands:{en:'Sample',ar:'نموذج'},markers:{en:'Sample',ar:'نموذج'},provenance:'original',source_reference:'sample'}}}],
});
describe('uncertain selection reconciliation', () => {
  it('accepts only a newer authoritative revision with the exact binding', () => {
    expect(matchesAcknowledgedSelection(configuration(),'dial',body)).toBe(true);
    expect(matchesAcknowledgedSelection({...configuration(),revision:7},'dial',body)).toBe(false);
    expect(matchesAcknowledgedSelection({...configuration(),revision:6},'dial',body)).toBe(false);
  });
  it.each(['brand_id','base_model','caliber'] as const)('does not conflate another %s', key => {
    expect(matchesAcknowledgedSelection({...configuration(),[key]:'other'},'dial',body)).toBe(false);
  });
  it('does not conflate another component, option revision, reference attachment or kind', () => {
    for(const mismatch of [{component:'case' as const},{option_id:'other'},{option_revision:4},{reference_ids:['a']}]) {
      expect(matchesAcknowledgedSelection(configuration(),'dial',{...body,...mismatch})).toBe(false);
    }
    expect(matchesAcknowledgedSelection(configuration(),'material',body)).toBe(false);
  });
});
