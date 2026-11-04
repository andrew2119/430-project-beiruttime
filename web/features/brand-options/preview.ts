import type { Component, Configuration, Option } from '@contracts/contracts-catalog/options';
export type PreviewPalette = {case:string;bezel:string;dial:string;hands:string;markers:string;strap:string};
export function previewPalette(config:Configuration|null, selected?:Option):PreviewPalette {
  const palette:PreviewPalette={case:'var(--surface)',bezel:'var(--accent)',dial:'#243c54',hands:'#e5d9bb',markers:'#e5d9bb',strap:'var(--accent-soft)'};
  const apply=(component:Component,swatch:unknown)=>{
    if(typeof swatch!=='string'||!/^#[\da-f]{6}$/i.test(swatch))return;
    switch(component) {
      case 'case':palette.case=swatch;break;
      case 'bezel':palette.bezel=swatch;break;
      case 'dial':palette.dial=swatch;break;
      case 'hands':palette.hands=swatch;break;
      case 'markers':palette.markers=swatch;break;
      case 'strap':case 'bracelet':palette.strap=swatch;break;
    }
  };
  for(const choice of config?.selections??[]) {
    if(choice.kind==='color'&&'swatch' in choice.definition.details)apply(choice.component,choice.definition.details.swatch);
  }
  if(selected?.kind==='color')apply(selected.component,selected.details.swatch);
  return palette;
}
