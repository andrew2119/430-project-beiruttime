'use client';
/** Shared CP Settings Switch recipe (settings-parts.tsx). */
export function Switch({id,checked,onChange,label,disabled}:{id?:string;checked:boolean;onChange:(checked:boolean)=>void;label:string;disabled?:boolean}) {
  return <button id={id} type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={()=>onChange(!checked)} className="proto-set-switch"><span className={`pg-view-switch${checked?' pg-view-switch-active':''}`} aria-hidden="true"><span className={`pg-view-switch-knob${checked?' pg-view-switch-knob-active':''}`}/></span></button>;
}
