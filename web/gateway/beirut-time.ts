const zone='Asia/Beirut';
const formatter=new Intl.DateTimeFormat('en-GB',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23',numberingSystem:'latn'});
export type BeirutInstant={local:string;utc:string;offset:string;time_zone:'Asia/Beirut'};
export class CivilTimeError extends Error {constructor(public code:'invalid_beirut_time'|'ambiguous_beirut_time'){super(code);}}
function parts(time:number){
  const values=Object.fromEntries(formatter.formatToParts(time).filter(part=>part.type!=='literal').map(part=>[part.type,part.value]));
  return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}:${values.second}`;
}
function nominal(local:string){
  const [year,month,day,hour,minute]=local.split(/[-T:]/).map(Number);
  const value=new Date(0);value.setUTCFullYear(year,month-1,day);value.setUTCHours(hour,minute,0,0);
  return value;
}
export function interpretBeirut(local:unknown):BeirutInstant {
  if(typeof local!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(local))throw new CivilTimeError('invalid_beirut_time');
  const base=nominal(local);
  if(!Number.isFinite(base.getTime())||base.toISOString().slice(0,16)!==local)throw new CivilTimeError('invalid_beirut_time');
  // Discover offsets around this civil date from the timezone database, not a fixed offset.
  const offsets=new Set<number>();
  for(let hours=-36;hours<=36;hours+=6){
    const sample=base.getTime()+hours*3600000;
    const localParts=parts(sample);
    offsets.add(nominal(localParts.slice(0,16)).getTime()+Number(localParts.slice(-2))*1000-sample);
  }
  const candidates=[...offsets].map(offset=>({offset,time:base.getTime()-offset})).filter(value=>parts(value.time)===`${local}:00`);
  if(candidates.length!==1)throw new CivilTimeError(candidates.length?'ambiguous_beirut_time':'invalid_beirut_time');
  const {offset,time}=candidates[0];
  const seconds=Math.abs(offset)/1000;
  const offsetText=`${offset<0?'-':'+'}${String(Math.floor(seconds/3600)).padStart(2,'0')}:${String(Math.floor(seconds/60)%60).padStart(2,'0')}${seconds%60?':'+String(seconds%60).padStart(2,'0'):''}`;
  return {local,utc:new Date(time).toISOString(),offset:offsetText,time_zone:zone};
}
