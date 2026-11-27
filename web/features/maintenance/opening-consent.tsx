'use client';
import {useEffect,useRef,useState} from 'react';
import {Button,Checkbox,State} from '@beirut-time/ui/foundation';
import type {MaintenanceResultV1} from '@contracts/contracts-service/maintenance/v1';
import {ApiError} from '@/lib/api/client';
import {useLocale} from '@/shell/locale-context';
import {call} from './common';
import type {OperationBinding,OperationJournal} from './scoped-operation';

type Command={operation_id:string;request_revision:number;expected_revision:number;opening_permitted:boolean;no_polish:boolean};
type Receipt=Command & {request_id:string;buyer_id:string;organization_id:string;watch_id:string;revision:number;recorded_at:string};
const text={
  en:{title:'Diagnostic opening',intro:'Choose whether the assessor may open the watch and whether you prefer no polishing. This does not accept a fee.',load:'Check opening preferences',open:'Permit diagnostic opening',no:'Prefer no polishing',save:'Save preferences',retry:'Retry the same preferences',saved:'Opening preferences recorded.',error:'Opening preferences could not be verified. Check again before making changes.'},
  ar:{title:'فتح الساعة للتشخيص',intro:'اختر ما إذا كان يجوز للمختص فتح الساعة للتشخيص وما إذا كنت تفضّل عدم تلميعها. لا يُعدّ ذلك قبولاً لأي رسوم.',load:'تحقّق من تفضيلات فتح الساعة',open:'أسمح بفتح الساعة للتشخيص',no:'أفضّل عدم التلميع',save:'حفظ التفضيلات',retry:'أعد إرسال التفضيلات نفسها',saved:'تم تسجيل تفضيلات فتح الساعة.',error:'تعذّر التحقق من التفضيلات. تحقّق مجددًا قبل إجراء أي تغيير.'},
};

export function OpeningConsent({scope,receipt,blocked,journal}:{scope:string;receipt:MaintenanceResultV1;blocked:boolean;
  journal:OperationJournal}) {
  const t=text[useLocale()];
  const [current,setCurrent]=useState<Receipt|null|undefined>();
  const [opening,setOpening]=useState(false),[noPolish,setNoPolish]=useState(true);
  const [busy,setBusy]=useState(false),[error,setError]=useState(false),[saved,setSaved]=useState(false);
  const pending=useRef<Command|null>(null), inFlight=useRef(false);
  const life=useRef<AbortController|null>(null);
  useEffect(()=>()=>life.current?.abort(),[]);
  const path=`maintenance/requests/${encodeURIComponent(receipt.request_id)}/opening-consent`;
  function verify(value:Receipt) {
    if (value.request_id!==receipt.request_id || value.buyer_id!==receipt.actor_id || value.watch_id!==receipt.watch_id ||
        value.organization_id!==receipt.organization_id || value.request_revision!==receipt.revision ||
        !Number.isSafeInteger(value.revision) || value.revision<1 || typeof value.opening_permitted!=='boolean' || typeof value.no_polish!=='boolean') {
      throw Error('opening_consent_binding');
    }
  }
  async function load() {
    if(blocked || inFlight.current || pending.current) return;
    inFlight.current=true;setBusy(true);setError(false);setCurrent(undefined);setSaved(false);
    const controller=new AbortController();life.current=controller;
    try {
      const value=await call<Receipt>(scope,path,{signal:controller.signal});
      if(controller.signal.aborted)return;
      verify(value);setCurrent(value);setOpening(value.opening_permitted);setNoPolish(value.no_polish);
    } catch(e) {
      if(controller.signal.aborted)return;
      if(e instanceof ApiError && e.status===404 && e.code==='opening_preference_missing') setCurrent(null);
      else setError(true);
    } finally {inFlight.current=false;if(!controller.signal.aborted)setBusy(false);}
  }
  async function save() {
    if(inFlight.current || current===undefined || (blocked&&!pending.current)) return;
    const command=pending.current??{operation_id:crypto.randomUUID(),request_revision:receipt.revision,
      expected_revision:current?.revision??0,opening_permitted:opening,no_polish:noPolish};
    const binding:OperationBinding={kind:'preference',operation_id:command.operation_id,owner:receipt.actor_id,record:receipt.request_id,
      organization:receipt.organization_id,expected_revision:command.expected_revision,source_revision:command.request_revision};
    if(!journal.begin(binding))return;
    pending.current=command;inFlight.current=true;setBusy(true);setError(false);setSaved(false);
    const controller=new AbortController();life.current=controller;
    try {
      const value=await call<Receipt>(scope,path,{signal:controller.signal,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});
      if(controller.signal.aborted)return;
      verify(value);
      if(value.operation_id!==command.operation_id || value.revision!==command.expected_revision+1 ||
        value.opening_permitted!==command.opening_permitted || value.no_polish!==command.no_polish) throw Error('opening_consent_receipt');
      pending.current=null;if(journal.resolve(binding)){setCurrent(value);setSaved(true);}
    } catch(e) {
      if(controller.signal.aborted)return;
      if(e instanceof ApiError && [401,403,404].includes(e.status)) {
        pending.current=null;setCurrent(undefined);setOpening(false);setNoPolish(true);
      }
      setError(true);
    } finally {inFlight.current=false;if(!controller.signal.aborted)setBusy(false);}
  }
  return <section><h2 className="bt-heading">{t.title}</h2><p>{t.intro}</p>
    {current===undefined?<Button busy={busy} disabled={blocked} onClick={()=>void load()}>{t.load}</Button>:<>
      <Checkbox label={t.open} checked={opening} onCheckedChange={setOpening} disabled={blocked||busy||!!pending.current}/>
      <Checkbox label={t.no} checked={noPolish} onCheckedChange={setNoPolish} disabled={blocked||busy||!!pending.current}/>
      <Button busy={busy} disabled={blocked&&!pending.current} onClick={()=>void save()}>{pending.current?t.retry:t.save}</Button>
    </>}
    {error&&<State headingLevel={3} kind="error" title={t.error} body={t.intro}/>}
    {saved&&<p role="status">{t.saved}</p>}
  </section>;
}
