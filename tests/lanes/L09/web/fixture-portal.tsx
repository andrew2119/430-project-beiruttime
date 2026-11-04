'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { beginSession, signOut } from '@/features/identity/session';
import { Button, Card, Input } from '@beirut-time/ui';
import { useLocale } from '@/shell/locale-context';

declare global { interface Window { __l09FixtureSignIn?:(email:string)=>Promise<boolean> } }
// L09_CONTRACT_FIXTURE_ONLY — copied temporarily, never part of a product route.
export default function FixturePortal() {
  const locale=useLocale();
  const router=useRouter();
  const [email,setEmail]=useState('buyer@example.invalid');
  const [password,setPassword]=useState('CONTRACT-ONLY-PASSWORD');
  const [destination,setDestination]=useState('/operations/moderation');
  const [pending,setPending]=useState(false);
  const [error,setError]=useState(false);
  useEffect(()=>{
    // Test-controller bridge survives client navigation only; authority still comes
    // from the explicit fixture login API, never a caller-supplied principal.
    window.__l09FixtureSignIn=async address=>{await beginSession('login',JSON.stringify({email:address,password:'CONTRACT-ONLY-PASSWORD'}),crypto.randomUUID());return true;};
  },[]);
  async function login(event:React.FormEvent) {
    event.preventDefault();if(pending)return;
    setPending(true);setError(false);
    try {await beginSession('login',JSON.stringify({email,password}),crypto.randomUUID());router.push(`/${locale}${destination}`);}
    catch {setError(true);}finally {setPending(false);}
  }
  return <div className="ops-page"><Card><h1>Contract fixture proof / اختبار عقد الخدمة</h1><p>Dependency transport fixtures only. Real L09 commands use isolated databases. This is not marketplace authority or final connected acceptance. No custody receipt or technical pass is created.</p><form className="ops-form" onSubmit={login} autoComplete="off"><label>Sample profile email<Input type="email" required value={email} onChange={event=>setEmail(event.target.value)}/></label><label>Fixture-only password<Input type="password" required value={password} onChange={event=>setPassword(event.target.value)}/></label><label>Destination<select value={destination} onChange={event=>setDestination(event.target.value)}><option value="/operations/moderation">Moderation</option><option value="/operations/dashboard">Operations desk</option><option value="/business-intake">Technical intake</option></select></label><Button type="submit" disabled={pending}>Sign in through the session API</Button></form><Button type="button" className="button-secondary" onClick={()=>void signOut()}>Sign out through the session API</Button>{error&&<p role="alert">Fixture sign-in was denied or unavailable.</p>}</Card></div>;
}
