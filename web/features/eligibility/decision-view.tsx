'use client';
import { useRef, useState } from 'react';
import { Button, Card, Input, Radio, State, Textarea, formatNumber } from '@beirut-time/ui/foundation';
import type { EligibilityCommand, EligibilityResult } from '@contracts/contracts-eligibility/decisions';
import { normalizeDigits } from '@beirut-time/i18n';
import { ApiError } from '@/lib/api/client';
import { useLocale } from '@/shell/locale-context';
import { authenticatedRequest } from '../identity/session';
import en from './en.json';
import ar from './ar.json';
const path='/api/web/v1/eligibility/v1/eligibility-decisions';
export function DecisionView({fingerprint}:{fingerprint:string}) {
  const locale=useLocale(),t=locale==='ar'?ar:en;
  const [verdict,setVerdict]=useState<'eligible'|'not_eligible'|'correction'>('correction');
  const [pending,setPending]=useState(false),[locked,setLocked]=useState(false);
  const [result,setResult]=useState<EligibilityResult|null>(null),[error,setError]=useState(false);
  const [reference,setReference]=useState<string|null>(null);
  const operation=useRef<EligibilityCommand|null>(null);
  async function submit(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault();if(pending)return;setPending(true);setError(false);setResult(null);
    try{
      if(!operation.current){const data=new FormData(event.currentTarget);operation.current={schema_version:'eligibility-command.v1',operation_id:crypto.randomUUID(),consent_id:String(data.get('consent')),expected_revision:Number(normalizeDigits(String(data.get('revision')))),kind:'review',verdict,reason:String(data.get('reason'))};}
      setReference(operation.current.operation_id);
      const answer=await authenticatedRequest<EligibilityResult>(path,{method:'POST',accessFingerprint:fingerprint,headers:{'Content-Type':'application/json'},body:JSON.stringify(operation.current)});
      setResult(answer);setLocked(answer.state==='pending');
      if(answer.state!=='pending')operation.current=null;
    }catch(failure){setError(true);if(failure instanceof ApiError&&[400,404,409,422].includes(failure.status)){operation.current=null;setLocked(false);}else setLocked(true);}
    finally{setPending(false);}
  }
  return <Card><h2 className="bt-heading">{t.title}</h2><p className="bt-text">{t.scope}</p><form className="consent-stack" onSubmit={submit}>
    <fieldset className="consent-fields" disabled={pending||locked}>
      <Input label={t.consent} name="consent" required/>
      <Input label={t.revision} name="revision" inputMode="numeric" defaultValue="0" required/>
      <Radio name="verdict" label={t.eligible} checked={verdict==='eligible'} onCheckedChange={()=>setVerdict('eligible')}/>
      <Radio name="verdict" label={t.not_eligible} checked={verdict==='not_eligible'} onCheckedChange={()=>setVerdict('not_eligible')}/>
      <Radio name="verdict" label={t.correction} checked={verdict==='correction'} onCheckedChange={()=>setVerdict('correction')}/>
      <Textarea label={t.reason} hint={t.privateHint} name="reason" required/>
    </fieldset>
    {reference&&<p className="bt-caption">{t.reference}: <bdi dir="ltr">{reference}</bdi></p>}
    <Button type="submit" busy={pending} disabled={pending}>{locked?t.retry:t.submit}</Button>
  </form>{error&&<State kind="error" title={t.error} body={t.recovery}/>}{result&&<State title={t[result.state]} body={result.state==='pending'?t.recovery:t.receipt}><p className="bt-caption">{t.reference}: <bdi dir="ltr">{result.operation_id}</bdi></p><p className="bt-number">{t.revision}: {formatNumber(result.revision,locale)}</p></State>}
  </Card>;
}
