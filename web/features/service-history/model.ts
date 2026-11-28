import type { Selection } from './read';
import type { PublicationResult } from './publication';
export type HistoryState = {watch:string;revision:string;selection:Selection|null;invalid:boolean;selected:string[];publication:PublicationResult|null};
export const initialHistoryState:HistoryState={watch:'',revision:'0',selection:null,invalid:false,selected:[],publication:null};
type Patch = {type:'patch';patch:Partial<HistoryState>} | {type:'selected';update:(previous:string[])=>string[]} | {type:'language'};
/** Language changes have no command or persistence side effects. */
export function historyReducer(state:HistoryState,action:Patch):HistoryState {
  if(action.type==='language')return state;
  if(action.type==='selected')return {...state,selected:action.update(state.selected)};
  return {...state,...action.patch};
}
