export type Attempt = Readonly<{body:string;operation:string}>;
export type Fields = {job:string;selected:string;kind:string;note:string;nextActor:string;nextAction:string;line:string;part:string;quantity:string;disposition:string;before:string;after:string;beforeAt:string;afterAt:string;method:string};
export type Form = {fields:Fields;attempt:Attempt|null};
export const initialForm:Form = {fields:{job:'',selected:'',kind:'progress',note:'',nextActor:'',nextAction:'',line:'',part:'',quantity:'1',disposition:'installed',before:'',after:'',beforeAt:'',afterAt:'',method:''},attempt:null};
export type FormAction = {type:'field';field:keyof Fields;value:string}|{type:'prepare';attempt:Attempt}|{type:'acknowledged';operation:string}|{type:'language'};
/** Locale changes leave the mounted private draft and uncertain operation intact. */
export function formReducer(state:Form,action:FormAction):Form {
  if (action.type==='language') return state;
  if (action.type==='prepare') return state.attempt ? state : {...state,attempt:Object.freeze({...action.attempt})};
  if (action.type==='acknowledged') return state.attempt?.operation===action.operation ? {...state,attempt:null} : state;
  if (state.attempt) return state;
  return {...state,fields:{...state.fields,[action.field]:action.value}};
}
