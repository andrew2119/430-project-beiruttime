import type { Command, Counter, Economics, Operation } from '@contracts/contracts-pricing/counteroffers';
export function dollars(value:string):number|null {
  if (!/^(?:0|[1-9]\d{0,10})(?:\.\d{1,2})?$/.test(value)) return null;
  const [whole,fraction=''] = value.split('.');
  const cents = Number(whole)*100+Number(fraction.padEnd(2,'0'));
  return Number.isSafeInteger(cents)&&cents>0&&cents<=9_000_000_000_000 ? cents : null;
}
export function commandFor(counter:Counter,actor:string,kind:Command['kind'],economics:Economics,reviewed:boolean,operation:string,sourceRevision:number,authorityRevision:number):Command {
  return {schema_version:'counteroffers.v1',operation_id:operation,subject_id:counter.subject_id,
    watch_id:counter.watch_id,actor_id:actor,organization_id:counter.organization_id,
    expected_revision:counter.revision,source_revision:sourceRevision,authority_revision:authorityRevision,kind,economics,
    reviewed_revision:reviewed?counter.revision:null};
}

export type BoundTerms = Readonly<{
  quote_id:string; quote_revision:number; terms_revision:number;
  en:Readonly<{terms:string; returns:string; assurance:string}>;
  ar:Readonly<{terms:string; returns:string; assurance:string}>;
  support_href:string;
}>;
export function termsMatch(terms:BoundTerms|undefined,economics:Economics|undefined):boolean {
  return !!terms && !!economics && terms.quote_id===economics.quote_id &&
    terms.quote_revision===economics.quote_revision && terms.terms_revision===economics.terms_revision &&
    [terms.en.terms,terms.en.returns,terms.en.assurance,terms.ar.terms,terms.ar.returns,terms.ar.assurance].every(text=>text.trim().length>0) &&
    /^\/(?![\/\\])[^\\\s]*$/.test(terms.support_href);
}
export function permissionDenied(error:unknown):boolean {
  if (!error || typeof error!=='object') return false;
  const value=error as {status?:number;code?:string};
  return value.status===401 || value.status===403 || value.code==='denied' || value.code==='forbidden';
}

export function operationMatches(answer:Operation,command:Command):boolean {
  return answer.operation_id===command.operation_id && answer.subject_id===command.subject_id &&
    answer.watch_id===command.watch_id && answer.actor_id===command.actor_id &&
    answer.organization_id===command.organization_id && answer.expected_revision===command.expected_revision &&
    (!answer.current || (answer.current.subject_id===command.subject_id && answer.current.watch_id===command.watch_id));
}
export function currentCounter(read:Counter|null|undefined,returned:Counter|null,denied:boolean,subjectId:string,watchId:string):Counter|null|undefined {
  if(denied)return null;
  const matches=(value:Counter|null|undefined)=>value?.subject_id===subjectId && value.watch_id===watchId;
  const scopedRead=matches(read)?read:null;
  return matches(returned) && returned && (!scopedRead || returned.revision>=scopedRead.revision)?returned:scopedRead;
}
