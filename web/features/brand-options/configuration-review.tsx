'use client';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button, Card, State, StatusBadge } from '@beirut-time/ui';
import { authenticatedRequest } from '@/features/identity/session';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { ApiError } from '@/lib/api/client';
import { configurationField } from './configuration-copy';
import type { Validation } from '@contracts/contracts-catalog/request-drafts/v2';
export type MovementBinding={id:string;revision:number};
export const configurationApi={
  movement:(brand:string,signal?:AbortSignal)=>authenticatedRequest<{selection:MovementBinding|null}>(`/api/web/v1/catalog/v1/options/movement/selections/current?brand_id=${encodeURIComponent(brand)}`,{signal}),
  validate:(id:string,revision:number,movement:MovementBinding)=>authenticatedRequest<Validation>(`/api/web/v1/catalog/v1/configurations/${encodeURIComponent(id)}/validate`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({configuration_revision:revision,movement_selection_id:movement.id,movement_revision:movement.revision})}),
};
export default function ConfigurationReview({id,revision,brand,sourcesCurrent=true}:{id:string;revision:number;brand:string;sourcesCurrent?:boolean}){
 const locale=useLocale(),ar=locale==='ar',access=useAccessContext();
 const movement=useQuery({queryKey:['movement-selection',access.fingerprint,brand],queryFn:({signal})=>configurationApi.movement(brand,signal),retry:false});
 const binding=JSON.stringify([access.fingerprint,id,revision,movement.data?.selection?.id,movement.data?.selection?.revision]);
 const[receipt,setReceipt]=useState<{binding:string;value:Validation}|null>(null),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false);
 const result=receipt&&receipt.binding===binding&&!movement.error&&(sourcesCurrent||receipt.value.status!=='valid')?receipt.value:null;
 const t=ar?{title:'تحقق من الأبعاد الخمسة',body:'اختر الحركة أدناه ثم تحقق من التركيبة الحالية. هذا ليس قبولاً لسعر أو تأكيداً للجدوى الفنية.',check:'تحقق من الاختيارات الحالية',reload:'تحديث الحركة',missing:'احفظ اختيار الحركة أولاً.',error:'تعذر تأكيد الاختيارات. أعد المحاولة أو راجع الأبعاد المحددة.',valid:'تركيبة مدعومة للمراجعة',incompatible:'تركيبة غير متوافقة',parts_unavailable:'قطع غير متوفرة',manual_assessment:'تحتاج تقييماً يدوياً'}:{title:'Check all five dimensions',body:'Choose the movement below, then validate the current combination. This is not price acceptance or a physical feasibility pass.',check:'Validate current choices',reload:'Refresh movement',missing:'Save a movement selection first.',error:'Choices could not be confirmed. Retry or review the highlighted dimensions.',valid:'Supported for review',incompatible:'Incompatible combination',parts_unavailable:'Parts unavailable',manual_assessment:'Manual assessment required'};
 async function validate(){if(!movement.data?.selection)return;setBusy(true);setError(null);try{setReceipt({binding,value:await configurationApi.validate(id,revision,movement.data.selection)});}catch(e){setReceipt(null);setError(e);}finally{setBusy(false);}}
 const fields=error instanceof ApiError?error.details.fields:result?.fields;
 return <Card className="bo-validation"><h2>{t.title}</h2><p>{t.body}</p>{movement.isPending?<State kind="loading" title={t.title} body={t.reload}/>:!movement.data?.selection&&<p role="status">{movement.error?t.error:t.missing}</p>}
 <div><Button disabled={busy||!movement.data?.selection} onClick={()=>void validate()}>{t.check}</Button><Button variant="outline" onClick={()=>void movement.refetch()}>{t.reload}</Button></div>
 {result&&<p role="status"><StatusBadge hue={result.status==='valid'?'green':'orange'}>{t[result.status]}</StatusBadge></p>}
 {!!error&&<p role="alert">{t.error}</p>}{!!fields&&typeof fields==='object'&&<ul>{Object.entries(fields).map(([name,reason])=><li key={name}>{configurationField(locale,name,reason)}</li>)}</ul>}
 </Card>;
}
