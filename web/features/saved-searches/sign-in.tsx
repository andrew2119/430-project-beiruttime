'use client';
import { useRef, useState } from 'react';
import { Button, Dialog, DialogContent, DialogTrigger, Input } from '@beirut-time/ui/foundation';
import { beginSession } from '@/features/identity/session';
import { useLocale } from '@/shell/locale-context';
export function SignIn({label,onIntent,onCancel}:{label:string;onIntent:()=>void;onCancel:()=>void}) {
  const locale=useLocale(),ar=locale==='ar';
  const [open,setOpen]=useState(false),[email,setEmail]=useState(''),[password,setPassword]=useState(''),[pending,setPending]=useState(false),[error,setError]=useState(false);
  const attempt=useRef<{body:string;key:string}|null>(null),busy=useRef(false);
  return <Dialog open={open} onOpenChange={value=>{if(!busy.current){setOpen(value);if(!value){setPassword('');attempt.current=null;onCancel();}}}}>
    <DialogTrigger>{label}</DialogTrigger>
    <DialogContent title={label} closeLabel={ar?'إغلاق':'Close'} description={ar?'يبقى البحث المدخل هنا. تسجيل الدخول لا يحفظه تلقائياً.':'Your entered search stays here. Signing in does not save it automatically.'}>
      <form className="saved-search-form" onSubmit={event=>{event.preventDefault();if(busy.current)return;busy.current=true;setPending(true);setError(false);onIntent();const body=JSON.stringify({email,password});if(attempt.current?.body!==body)attempt.current={body,key:crypto.randomUUID()};void beginSession('login',body,attempt.current.key).then(()=>{setPassword('');attempt.current=null;setOpen(false);}).catch(()=>{onCancel();setError(true);}).finally(()=>{busy.current=false;setPending(false);});}}>
        <Input label={ar?'البريد الإلكتروني':'Email address'} type="email" value={email} onValueChange={setEmail} autoComplete="email" disabled={pending} required/>
        <Input label={ar?'كلمة المرور':'Password'} type="password" value={password} onValueChange={setPassword} autoComplete="current-password" disabled={pending} required/>
        {error&&<p role="alert">{ar?'تعذّر تسجيل الدخول. راجع التفاصيل وأعد المحاولة.':'Sign-in could not be confirmed. Check your details and retry.'}</p>}
        <Button type="submit" disabled={pending}>{pending?(ar?'جارٍ التحقق…':'Checking…'):label}</Button>
      </form>
    </DialogContent>
  </Dialog>;
}
