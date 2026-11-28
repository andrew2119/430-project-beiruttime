export type Draft={listing:string;opening:string;step:string;bands:{from:string;step:string}[];starts:string;ends:string;time_zone:'Asia/Beirut'};
export const empty:Draft={listing:'',opening:'',step:'',bands:[],starts:'',ends:'',time_zone:'Asia/Beirut'};
// Restore only public draft fields. Private reserve never enters browser storage.
export function restoreDraft(saved:string|null):Draft {
  if(!saved)return {...empty};
  try {
    const value:unknown=JSON.parse(saved);
    if(!value||typeof value!=='object'||Array.isArray(value))return {...empty};
    const fields=value as Record<string,unknown>;
    const text=(key:string)=>typeof fields[key]==='string'?fields[key] as string:'';
    const context={listing:text('listing'),starts:fields.time_zone==='Asia/Beirut'?text('starts'):'',ends:fields.time_zone==='Asia/Beirut'?text('ends'):'',time_zone:'Asia/Beirut' as const};
    // Historic non-USD input is not silently reinterpreted as dollars.
    if(fields.currency!==undefined&&fields.currency!=='USD')return {...empty,...context};
    const bands=Array.isArray(fields.bands)?fields.bands.slice(0,19).filter(band=>band&&typeof band==='object'&&typeof band.from==='string'&&typeof band.step==='string').map(band=>({from:band.from as string,step:band.step as string})):[];
    return {...context,opening:text('opening'),step:text('step'),bands};
  }catch{return {...empty};}
}
