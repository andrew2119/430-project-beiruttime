'use client';
import { Button, Input, Label, Select, Textarea } from '@beirut-time/ui/foundation';
import type { Ref } from 'react';
import type { Command, Context } from '@contracts/contracts-trust/disputes/v1';
import type { Locale } from '@/lib/i18n';
import type { Draft } from './model';
import { copy } from './copy';

export function DisputeFields({locale,draft,onDraft,kind,onKind,context,locked,fileInput,onSubmit}:{locale:Locale;draft:Draft;onDraft:(draft:Draft)=>void;kind:Command['kind'];onKind:(kind:Command['kind'])=>void;context:Context;locked:boolean;fileInput:Ref<HTMLInputElement>;onSubmit:()=>void}) {
 const t=copy[locale];
 return <form onSubmit={event=>{event.preventDefault();onSubmit();}}>
  <Select label={t.action} id="dispute-action" value={kind} onValueChange={value=>onKind(value as Command['kind'])} messages={{placeholder:t.action,filter:t.action,emptyTitle:t.empty,emptyBody:t.empty,close:t.load,loading:t.loading,errorTitle:t.unavailable,errorBody:t.unavailable,retry:t.retry}} disabled={locked} options={context.actions.map(action=>({value:action,label:t[action]}))}/>
  <Textarea label={t.reason} id="dispute-reason" required value={draft.reason} disabled={locked} onValueChange={value=>onDraft({...draft,reason:value.slice(0,4000)})}/>
  {kind==='refund'&&<Input label={t.amount} id="dispute-amount" inputMode="decimal" value={draft.amount} disabled={locked} onValueChange={value=>onDraft({...draft,amount:value})}/>}
  <Label htmlFor="dispute-file">{t.file}</Label><input className="bt-input" ref={fileInput} id="dispute-file" type="file" accept="image/jpeg,image/png,application/pdf" disabled={locked} onChange={event=>onDraft({...draft,file:event.target.files?.[0]??null})}/>
  {draft.file&&<p dir="auto">{draft.file.name}</p>}
  {draft.operation&&<p>{t.reference}: <bdi dir="ltr">{draft.operation.operation_id}</bdi></p>}
  <Button type="submit" disabled={locked||!context.actions.includes(kind)}>{t.submit}</Button>
 </form>;
}
