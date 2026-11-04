import { describe, expect, it } from 'vitest';
import type { Component, Configuration, Option } from '@contracts/contracts-catalog/options';
import { previewPalette } from './preview';
const color=(component:Component,swatch:string):Option=>({id:component,revision:1,kind:'color',component,label:{en:'Sample',ar:'نموذج'},base_models:['base'],calibers:['caliber'],available:true,
  details:{color:{en:'Sample',ar:'نموذج'},finish:{en:'Brushed',ar:'مصقول'},coating:null,swatch}});
function saved(...options:Option[]):Configuration {
  return {id:'configuration',brand_id:'brand',base_model:'base',caliber:'caliber',revision:1,state:'saved_not_submitted',feasibility:'not_assessed',reference_ids:[],updated_at:'2026-11-04T07:00:00Z',
    selections:options.map(option=>{const {id,revision,kind,...definition}=option;return {kind,component:option.component,option_id:id,option_revision:revision,reference_ids:[],definition,current:true};})};
}
describe('component-bound illustration colors',()=>{
  it('does not paint the dial when a case color is chosen',()=>{
    const palette=previewPalette(null,color('case','#a8afb0'));
    expect(palette.case).toBe('#a8afb0');expect(palette.dial).toBe('#243c54');
  });
  it('preserves saved component colors and changes only the active preview component',()=>{
    const palette=previewPalette(saved(color('case','#a8afb0'),color('bezel','#252b2a')),color('dial','#243c54'));
    expect(palette.case).toBe('#a8afb0');expect(palette.bezel).toBe('#252b2a');expect(palette.dial).toBe('#243c54');
  });
  it('binds hands, markers and strap colors to their respective illustration parts',()=>{
    const palette=previewPalette(saved(color('hands','#111111'),color('markers','#222222'),color('strap','#333333')));
    expect(palette.hands).toBe('#111111');expect(palette.markers).toBe('#222222');expect(palette.strap).toBe('#333333');
    expect(previewPalette(null,color('bracelet','#444444')).strap).toBe('#444444');
  });
  it('ignores injected CSS values rather than turning a swatch into a resource URL',()=>{
    expect(previewPalette(null,color('case','url(https://invalid.example/pixel)')).case).toBe('var(--surface)');
  });
});
