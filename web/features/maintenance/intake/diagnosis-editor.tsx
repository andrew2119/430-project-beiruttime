'use client';
import {useEffect,useRef,useState} from 'react';
import {Button,Card,Checkbox,Input,Radio,State,Textarea,formatNumber} from '@beirut-time/ui/foundation';
import {ApiError} from '@/lib/api/client';
import {useLocale} from '@/shell/locale-context';
import {useSession} from '@/features/identity/session';
import {validTestKeys} from '@contracts/contracts-service/test-keys/v1';
import {call} from '../common';
import {isReference} from '../submission';
import {sameOperation,type OperationBinding,type OperationJournal} from '../scoped-operation';

type Context={case_id:string;request_id:string;watch_id:string;actor_id:string;organization_id:string;
  expected_revision:number;assignment_revision:number;
  reviewed_intake:{intake_revision:number;receipt_id:string;receipt_revision:number;watch_revision:number;incident_revision:number}};
type Line={id:string;label:string;kind:'part'|'labor';mandatory:boolean;tests:string;finish:''|'none'|'polish'|'brush';area:string};
type Command=Context & {operation_id:string;diagnosis:string;
  lines:Pick<Line,'id'|'label'|'kind'|'mandatory'>[];required_tests:Record<string,string[]>;
  finish_requirements:Record<string,{area_id:string;action:'polish'|'brush'}[]>};
type Receipt=Command & {state:'assessed';revision:number;assessment_id:string};
const lineDraft=():Line=>({id:crypto.randomUUID(),label:'',kind:'labor',mandatory:true,tests:'',finish:'',area:''});
const words={
  en:{title:'Diagnosis and test plan',load:'Review current intake',diagnosis:'Technical diagnosis',line:'Repair line',label:'Work or part',part:'Part',labor:'Labour',mandatory:'Required repair line',tests:'Required tests, one exact key per line',testHelp:'Use 1 to 30 distinct keys without extra spaces at either end.',finish:'Finish impact',none:'No abrasive finish',polish:'Polishing',brush:'Brushing',area:'Assessed area reference',add:'Add repair line',remove:'Remove repair line',save:'Record diagnosis',retry:'Retry the original diagnosis',saved:'Diagnosis and required tests recorded.',stale:'The intake or diagnosis changed. Review the latest intake before trying again.',unknown:'The result could not be verified. Keep this reference and retry the same diagnosis.',unavailable:'Current assessment facts could not be verified.',receipt:'Reviewed custody receipt',revision:'Reviewed intake revision'},
  ar:{title:'التشخيص وخطة الاختبارات',load:'راجع الاستلام الحالي',diagnosis:'التشخيص الفني',line:'بند الإصلاح',label:'العمل أو القطعة',part:'قطعة',labor:'عمل',mandatory:'بند إصلاح إلزامي',tests:'الاختبارات المطلوبة، رمز دقيق واحد في كل سطر',testHelp:'أدخل من ١ إلى ٣٠ رمزًا مختلفًا دون مسافات زائدة في البداية أو النهاية.',finish:'أثر العمل على التشطيب',none:'دون كشط التشطيب',polish:'تلميع',brush:'صقل بالفرشاة',area:'مرجع المنطقة التي جرى تقييمها',add:'أضف بند إصلاح',remove:'أزل بند الإصلاح',save:'سجّل التشخيص',retry:'أعد إرسال التشخيص الأصلي',saved:'تم تسجيل التشخيص والاختبارات المطلوبة.',stale:'تغيّر الاستلام أو التشخيص. راجع أحدث سجل استلام قبل المحاولة مجددًا.',unknown:'تعذّر التحقق من النتيجة. احتفظ بالمرجع وأعد إرسال التشخيص نفسه.',unavailable:'تعذّر التحقق من بيانات التقييم الحالية.',receipt:'إيصال العهدة الذي تمت مراجعته',revision:'إصدار الاستلام الذي تمت مراجعته'},
};

export function DiagnosisEditor({scope,organization,caseId,intakeRevision,available,inherited,onDenied,journal}:{
  scope:string;organization:string;caseId:string;intakeRevision:number;available:boolean;inherited:OperationBinding|null;
  onDenied:(error:unknown)=>void;journal:OperationJournal;
}) {
  const locale=useLocale(),t=words[locale];
  const session=useSession();
  const [context,setContext]=useState<Context>();
  const [diagnosis,setDiagnosis]=useState(''),[lines,setLines]=useState<Line[]>([]);
  const [status,setStatus]=useState<'saved'|'stale'|'unknown'|'unavailable'>();
  const [busy,setBusy]=useState(false);
  const pending=useRef<Command|null>(null),busyRef=useRef(false);
  const life=useRef<AbortController|null>(null);
  useEffect(()=>()=>life.current?.abort(),[]);
  const query=new URLSearchParams({organization_id:organization});
  const base=`service-cases/${encodeURIComponent(caseId)}`;
  const owner=session?.access_fingerprint===scope?session.principal.actor.subject_id:undefined;
  const exactContext=(value:Context)=>value.case_id===caseId && value.actor_id===owner && value.organization_id===organization &&
    value.reviewed_intake?.intake_revision===intakeRevision &&
    [value.case_id,value.request_id,value.watch_id,value.reviewed_intake.receipt_id].every(isReference) &&
    [[value.expected_revision,0],[value.assignment_revision,1],[value.reviewed_intake.watch_revision,1],
      [value.reviewed_intake.receipt_revision,1],[value.reviewed_intake.incident_revision,0]].every(([value,min])=>Number.isSafeInteger(value)&&value>=min);
  const bindingFor=(command:Command):OperationBinding=>({kind:'diagnosis',operation_id:command.operation_id,owner:command.actor_id,
    record:command.case_id,organization:command.organization_id,expected_revision:command.expected_revision,
    source_revision:command.reviewed_intake.intake_revision});
  const canRetry=!!pending.current&&sameOperation(inherited??undefined,bindingFor(pending.current));
  const ready=available&&!inherited&&!!context&&exactContext(context);
  const valid=diagnosis.trim().length>0 && diagnosis.length<=2000 && lines.length>0 && lines.length<=40 &&
    lines.every(line=>line.label.trim().length>0&&line.label.length<=160&&validTestKeys(line.tests.split('\n'))&&
      (line.finish==='none'||(line.finish!==''&&isReference(line.area))));
  function update(id:string,change:Partial<Line>) {
    setLines(previous=>previous.map(line=>line.id===id?{...line,...change}:line));
  }
  function denied(error:unknown) {
    if(error instanceof ApiError && [401,403].includes(error.status)) onDenied(error);
  }
  async function load() {
    if(!available||inherited||busyRef.current||pending.current) return;
    busyRef.current=true;setBusy(true);setStatus(undefined);setContext(undefined);
    const controller=new AbortController();life.current=controller;
    try {
      const value=await call<Context>(scope,`${base}/diagnosis-context?${query}`,{signal:controller.signal});
      if(controller.signal.aborted)return;
      if(!exactContext(value)) throw Error('diagnosis_context_binding');
      setContext(value);setLines(previous=>previous.length?previous:[lineDraft()]);
    } catch(error) {if(!controller.signal.aborted){denied(error);setStatus('unavailable');}}
    finally {busyRef.current=false;if(!controller.signal.aborted)setBusy(false);}
  }
  async function submit() {
    if(busyRef.current||!owner||(pending.current?!canRetry:(!ready||!valid||!context)))return;
    const recovering=!!pending.current;
    const command:Command=pending.current??{...context!,operation_id:crypto.randomUUID(),diagnosis:diagnosis.trim(),
      lines:lines.map(({id,label,kind,mandatory})=>({id,label:label.trim(),kind,mandatory})),
      required_tests:Object.fromEntries(lines.map(line=>[line.id,line.tests.split('\n')])),
      finish_requirements:Object.fromEntries(lines.map(line=>[line.id,line.finish==='polish'||line.finish==='brush'
        ? [{area_id:line.area,action:line.finish}] : []]))};
    const binding=bindingFor(command);
    if(!journal.begin(binding))return;
    pending.current=command;busyRef.current=true;setBusy(true);setStatus(undefined);
    const controller=new AbortController();life.current=controller;
    try {
      let historical:Receipt|undefined;
      if(recovering) {
        try {historical=await call<Receipt>(scope,`${base}/diagnosis/operations/${encodeURIComponent(command.operation_id)}?${query}`,{signal:controller.signal});}
        catch(error) {if(!(error instanceof ApiError)||error.status!==404||error.code!=='diagnosis_operation_missing')throw error;}
      }
      if(controller.signal.aborted)return;
      const result=historical??await call<Receipt>(scope,`${base}/diagnosis?${query}`,{signal:controller.signal,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});
      if(controller.signal.aborted)return;
      if(result.operation_id!==command.operation_id || result.state!=='assessed'||result.case_id!==caseId ||
        result.actor_id!==owner||result.organization_id!==organization||result.watch_id!==command.watch_id||result.request_id!==command.request_id||
        result.revision!==command.expected_revision+1||result.expected_revision!==command.expected_revision||
        result.assignment_revision!==command.assignment_revision||result.diagnosis!==command.diagnosis||!isReference(result.assessment_id)||
        Object.entries(command.reviewed_intake).some(([key,value])=>result.reviewed_intake?.[key as keyof Context['reviewed_intake']]!==value)||
        result.lines?.length!==command.lines.length||command.lines.some(({id,label,kind,mandatory},index)=>{
          const line=result.lines[index];
          const expected=command.required_tests[id], received=result.required_tests?.[id];
          const expectedFinish=command.finish_requirements[id], receivedFinish=result.finish_requirements?.[id];
          return line?.id!==id||line.label!==label||line.kind!==kind||line.mandatory!==mandatory||
            received?.length!==expected.length||received.some((test,n)=>test!==expected[n])||
            receivedFinish?.length!==expectedFinish.length||receivedFinish.some((area,n)=>
              area.area_id!==expectedFinish[n].area_id||area.action!==expectedFinish[n].action);
        }))throw Error('diagnosis_receipt_binding');
      pending.current=null;if(journal.resolve(binding)){setStatus('saved');setContext(undefined);setDiagnosis('');setLines([]);}
    } catch(error) {
      if(controller.signal.aborted)return;
      denied(error);
      if(error instanceof ApiError&&[401,403].includes(error.status)) {
        setContext(undefined);pending.current=null;setDiagnosis('');setLines([]);setStatus('unavailable');
      } else if(error instanceof ApiError&&[400,409,422].includes(error.status)) {
        setContext(undefined);pending.current=null;setStatus('stale');
      } else setStatus('unknown');
    } finally {busyRef.current=false;if(!controller.signal.aborted)setBusy(false);}
  }
  if((!available||inherited)&&!canRetry)return null;
  return <Card><h2>{t.title}</h2>
    {!ready&&!pending.current&&<Button busy={busy} disabled={!available} onClick={()=>void load()}>{t.load}</Button>}
    {ready&&context&&<><p>{t.revision}: {formatNumber(context.reviewed_intake.intake_revision,locale)} · {t.receipt}: <bdi>{context.reviewed_intake.receipt_id}</bdi></p>
      <form onSubmit={event=>{event.preventDefault();void submit();}}><fieldset disabled={busy||!!pending.current}>
        <Textarea label={t.diagnosis} value={diagnosis} onValueChange={setDiagnosis}/>
        {lines.map((line,index)=><fieldset key={line.id}>
          <legend>{t.line} {formatNumber(index+1,locale)}</legend>
          <Input label={t.label} value={line.label} onValueChange={label=>update(line.id,{label})}/>
          <Radio label={t.labor} name={`${line.id}-kind`} checked={line.kind==='labor'} onCheckedChange={()=>update(line.id,{kind:'labor'})}/>
          <Radio label={t.part} name={`${line.id}-kind`} checked={line.kind==='part'} onCheckedChange={()=>update(line.id,{kind:'part'})}/>
          <Checkbox label={t.mandatory} checked={line.mandatory} onCheckedChange={mandatory=>update(line.id,{mandatory})}/>
          <Textarea label={t.tests} hint={t.testHelp} value={line.tests} onValueChange={tests=>update(line.id,{tests})}/>
          <fieldset><legend>{t.finish}</legend>
            {(['none','polish','brush'] as const).map(finish=><Radio key={finish} label={t[finish]} name={`${line.id}-finish`}
              checked={line.finish===finish} onCheckedChange={()=>update(line.id,{finish})}/>)}
          </fieldset>
          {(line.finish==='polish'||line.finish==='brush')&&<Input label={t.area} value={line.area} onValueChange={area=>update(line.id,{area})}/>}
          <Button type="button" disabled={lines.length===1} onClick={()=>setLines(previous=>previous.filter(value=>value.id!==line.id))}>{t.remove}</Button>
        </fieldset>)}
        <Button type="button" disabled={lines.length===40} onClick={()=>setLines(previous=>[...previous,lineDraft()])}>{t.add}</Button>
        <Button type="submit" disabled={!valid}>{t.save}</Button>
      </fieldset></form></>}
    {canRetry&&pending.current&&<><bdi>{pending.current.operation_id}</bdi><Button busy={busy} onClick={()=>void submit()}>{t.retry}</Button></>}
    {status==='saved'?<p role="status">{t.saved}</p>:status&&<State headingLevel={3} kind="error" title={t[status]} body={t.title}/>}
  </Card>;
}
