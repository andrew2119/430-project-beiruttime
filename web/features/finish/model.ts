import type { Area, Command, Decision, Detail } from '@contracts/contracts-service/finish';
export function permitsIntervention(area:Area) {
  return area.suitable && area.material_known && area.preservation_assessed && area.original!=='unknown' && area.coating==='absent' && area.plating==='absent' && area.engraving==='absent'
    && ((area.assessed_action==='brush' && area.desired==='brushed') || (area.assessed_action==='polish' && area.desired==='mirror'));
}
export function makeCommand(detail:Detail, decisions:Readonly<Record<string,Decision>>, operation:string):Command {
  const s=detail.source;
  if(s.areas.length<1 || s.areas.length>32 || new Set(s.areas.map(a=>a.area_id)).size!==s.areas.length) throw new Error('scope_mismatch');
  const choices=s.areas.map(a=>{
    const decision=decisions[a.area_id];
    if(!decision || (decision==='consent'&&!permitsIntervention(a))) throw new Error('scope_mismatch');
    return {area_id:a.area_id,decision};
  });
  return {schema_version:'finish.v1',operation_id:operation,subject_id:s.subject_id,watch_id:s.watch_id,actor_id:s.buyer_id,
    organization_id:s.organization_id,expected_revision:detail.revision,source_revision:s.source_revision,
    assessment_revision:s.assessment_revision,quote_id:s.quote_id,quote_revision:s.quote_revision,policy_revision:s.policy_revision,choices};
}

export function centsToDollars(cents:number):string {
  if(!Number.isSafeInteger(cents)||cents<0) throw new Error('invalid_amount');
  return `${Math.floor(cents/100)}.${String(cents%100).padStart(2,'0')}`;
}

function object(value:unknown):Record<string,unknown> {
  if(!value||typeof value!=='object'||Array.isArray(value)) throw new Error('invalid_response');
  return value as Record<string,unknown>;
}
function integer(value:unknown,min=0):value is number {return typeof value==='number'&&Number.isSafeInteger(value)&&value>=min;}
function uuid(value:unknown):value is string {return typeof value==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);}
function text(value:unknown,max:number):boolean {return typeof value==='string'&&Boolean(value.trim())&&value.length<=max;}
function oneOf(value:unknown,values:readonly unknown[]):boolean {return values.includes(value);}
export function validateDetail(value:unknown,subject:string):Detail {
  const d=object(value),s=object(d.source);
  const fail=()=>{throw new Error('invalid_response');};
  for(const key of ['subject_id','watch_id','buyer_id','organization_id','quote_id','commitment_id']) if(!uuid(s[key])) fail();
  for(const key of ['source_revision','assessment_revision','quote_revision','policy_revision']) if(!integer(s[key],1)) fail();
  if(s.subject_id!==subject||s.current!==true||s.assigned!==true||s.retained!==true||s.currency!=='USD'||!integer(s.total_minor)||s.total_minor>999999999999) fail();
  if(typeof s.valid_until!=='string'||!/(Z|[+-]\d\d:\d\d)$/.test(s.valid_until)||!Number.isFinite(Date.parse(s.valid_until))) fail();
  if(!integer(d.revision)||!Array.isArray(s.areas)||s.areas.length<1||s.areas.length>32||!Array.isArray(d.choices)) return fail();
  const terms=object(s.terms);
  if(!integer(terms.revision,1)||terms.support_path!=='/inbox') fail();
  for(const key of ['fee_en','fee_ar','return_en','return_ar','assurance_en','assurance_ar']) if(!text(terms[key],2000)) fail();
  const ids=new Set<string>();
  for(const value of s.areas) {
    const a=object(value);
    if(!uuid(a.area_id)||ids.has(a.area_id)) return fail();
    ids.add(a.area_id);
    for(const key of ['name_en','name_ar']) if(!text(a[key],160)) fail();
    for(const key of ['material_en','material_ar']) if(!text(a[key],300)) fail();
    for(const key of ['preservation_en','preservation_ar']) if(!text(a[key],1000)) fail();
    if(!oneOf(a.original,['brushed','mirror','mixed','unknown'])||!oneOf(a.desired,['brushed','mirror','preserve'])||
      !oneOf(a.coating,['absent','present','unknown'])||!oneOf(a.plating,['absent','thin','present','unknown'])||
      !oneOf(a.engraving,['absent','present','unknown'])||!oneOf(a.assessed_action,['polish','brush','no_polish'])||typeof a.suitable!=='boolean'||typeof a.material_known!=='boolean'||typeof a.preservation_assessed!=='boolean') fail();
  }
  const picked=new Set<string>();
  for(const value of d.choices) {
    const c=object(value);
    if(!uuid(c.area_id)||!ids.has(c.area_id)||picked.has(c.area_id)||!oneOf(c.decision,['consent','no_polish'])) return fail();
    picked.add(c.area_id);
  }
  if(picked.size!==0&&picked.size!==ids.size) fail();
  return value as Detail;
}
export function validateResult(value:unknown,command:Command):import('@contracts/contracts-service/finish').Result {
  const r=object(value);
  for(const key of ['schema_version','operation_id','subject_id','watch_id','actor_id','organization_id','expected_revision'] as const)
    if(r[key]!==command[key]) throw new Error('invalid_response');
  const recorded=r.state==='recorded'&&r.revision===command.expected_revision+1&&r.pending_reason===null&&r.next_actor===null;
  const pending=r.state==='pending'&&r.revision===command.expected_revision&&r.pending_reason==='source_unavailable'&&r.next_actor==='buyer';
  if((!recorded&&!pending)||r.next_review_at!==null) throw new Error('invalid_response');
  return value as import('@contracts/contracts-service/finish').Result;
}

export async function recoverOrRecord<T>(lookup:()=>Promise<T>,record:()=>Promise<T>,missing:(error:unknown)=>boolean):Promise<T> {
  try { return await lookup(); }
  catch(error) { if(!missing(error)) throw error; }
  return record();
}
