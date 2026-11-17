'use client';
import {useEffect} from 'react';
import {useRouter} from 'next/navigation';
import {useLocale} from '@/shell/locale-context';
import {localizePath,stripLocale} from '@/shell/paths';
import type {Locale} from '@/lib/i18n';

/** Update the root locale through a refresh of the same mounted route. */
export function changeLanguage(next:Locale,refresh:()=>void){
 const destination=new URL(window.location.href);
 destination.pathname=localizePath(destination.pathname,next);
 document.cookie=`bt-locale=${next}; Path=/; Max-Age=31536000; SameSite=Lax`;
 window.history.replaceState(window.history.state,'',destination.href);
 refresh();
}

export function useCancellationLocale(){
 const locale=useLocale();
 const router=useRouter();
 useEffect(()=>{
  function intercept(event:MouseEvent){
   if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
   const link=event.target instanceof Element?event.target.closest('a.locale-control'):null;
   if(!(link instanceof HTMLAnchorElement)||link.target||link.download)return;
   const destination=new URL(link.href,window.location.href);
   const next=/^\/(en|ar)(?=\/|$)/.exec(destination.pathname)?.[1];
   if(destination.origin!==window.location.origin||stripLocale(destination.pathname)!==stripLocale(window.location.pathname)||(next!=='en'&&next!=='ar'))return;
   event.preventDefault();
   event.stopPropagation();
   changeLanguage(next,()=>router.refresh());
  }
  document.addEventListener('click',intercept,true);
  return ()=>document.removeEventListener('click',intercept,true);
 },[router]);
 return {locale,changeLocale:(next:Locale)=>{if(next!==locale)changeLanguage(next,()=>router.refresh());}};
}
