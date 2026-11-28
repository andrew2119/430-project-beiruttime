import type { FieldProps } from './fields';
export type SelectOption = {value:string; label:string; disabled?:boolean};
export type SelectMessages = {placeholder:string; filter:string; emptyTitle:string; emptyBody:string; close:string; loading:string; errorTitle:string; errorBody:string; retry:string};
export type SelectProps = FieldProps & {value:string|null; onValueChange:(value:string)=>void; options:readonly SelectOption[]; messages:SelectMessages; name?:string; searchable?:boolean; loadGate?:()=>Promise<void>};
export type SelectEngagement = {open:boolean; focus:boolean; input:'pointer'|'keyboard'; edge:'first'|'last'};
export type SelectImplementationProps = SelectProps & {id:string; engagement:SelectEngagement};
