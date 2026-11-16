'use client';
import { useEffect, useState, useSyncExternalStore } from 'react';
import { Download } from 'lucide-react';
import type { Messages } from '@/lib/i18n';
import { Button, Popover, PopoverTrigger, PopoverContent, toast } from '@beirut-time/ui';
import { useInstallPrompt } from './install-prompt-provider';
const subscribe=(callback:()=>void)=>{window.addEventListener('online',callback);window.addEventListener('offline',callback);return()=>{window.removeEventListener('online',callback);window.removeEventListener('offline',callback);};};
/** The footer install row: no unsupported button, no duplicate event capture. */
export function PwaInstall({t}:{t:Messages}) {
 const {canInstall,promptInstall,isStandalone,isIOS}=useInstallPrompt();
 if(isStandalone||(!canInstall&&!isIOS))return null;
 if(canInstall)return <Button variant="ghost" className="pg-nav-item pg-profile-link" onClick={()=>void promptInstall()}><Download aria-hidden="true"/>{t.install}</Button>;
 return <Popover><PopoverTrigger asChild><Button variant="ghost" className="pg-nav-item pg-profile-link"><Download aria-hidden="true"/>{t.install}</Button></PopoverTrigger><PopoverContent side="right" align="end"><h2 className="text-sm font-semibold">{t.install}</h2><p className="mt-2 text-xs text-muted-foreground">{t.iosInstall}</p></PopoverContent></Popover>;
}
/** Existing online-first worker/update policy, using the shared banner/toast placement. */
export function Pwa({t}:{t:Messages}) {
 const online=useSyncExternalStore(subscribe,()=>navigator.onLine!==false,()=>true);
 const [waiting,setWaiting]=useState<ServiceWorker|null>(null);
 useEffect(()=>{
  let disposed=false;let interval:ReturnType<typeof setInterval>|undefined;let cleanup:(()=>void)|undefined;
  if(process.env.NODE_ENV==='production'&&'serviceWorker' in navigator){
   navigator.serviceWorker.register('/sw.js',{updateViaCache:'none'}).then(registration=>{
    if(disposed)return;
    const inspect=()=>{if(registration.waiting&&navigator.serviceWorker.controller)setWaiting(registration.waiting);};
    const found=()=>registration.installing?.addEventListener('statechange',inspect);
    inspect();registration.addEventListener('updatefound',found);cleanup=()=>registration.removeEventListener('updatefound',found);
    interval=setInterval(()=>{if(document.visibilityState==='visible')void registration.update().catch(()=>{});},3600000);
   }).catch(()=>{});
  }
  return()=>{disposed=true;if(interval)clearInterval(interval);cleanup?.();};
 },[]);
 useEffect(()=>{
  if(!waiting)return;
  const id=toast(t.update,{duration:Infinity,action:{label:t.updateAction,onClick:()=>{
   let reloaded=false;
   const reload=()=>{if(!reloaded){reloaded=true;location.reload();}};
   navigator.serviceWorker.addEventListener('controllerchange',reload,{once:true});
   waiting.postMessage('SKIP_WAITING');
   setTimeout(()=>{if(!reloaded)void navigator.serviceWorker.getRegistration().then(r=>r?.unregister()).finally(reload);},4000);
  }}});
  return()=>{toast.dismiss(id);};
 },[waiting,t.update,t.updateAction]);
 return !online?<div role="status" className="pg-offline-banner">{t.offline}</div>:null;
}
