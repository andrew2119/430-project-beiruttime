import type {Locale} from '@beirut-time/i18n';
import {localizePath,stripLocale} from './paths';
type Browser={location:{pathname:string;search:string;hash:string;origin:string};history:{replaceState(data:unknown,unused:string,url:string):void};document:{cookie:string;documentElement:{lang:string;dir:string}}};
export function applyLocale(next:Locale,browser:Browser=window){
  browser.document.cookie=`bt-locale=${next}; Path=/; Max-Age=31536000; SameSite=Lax`;
  browser.document.documentElement.lang=next;
  browser.document.documentElement.dir=next==='ar'?'rtl':'ltr';
  // Change the address without navigation, refresh, form serialization or private storage.
  browser.history.replaceState(null,'',localizePath(browser.location.pathname,next)+browser.location.search+browser.location.hash);
}
export function localeForLink(href:string,current:{origin:string;pathname:string}):Locale|null {
  try{
    const destination=new URL(href,current.origin);
    const locale=/^\/(en|ar)(?:\/|$)/.exec(destination.pathname)?.[1];
    return destination.origin===current.origin&&stripLocale(destination.pathname)===stripLocale(current.pathname)&&(locale==='en'||locale==='ar')?locale:null;
  }catch{return null;}
}
export function captureLocaleLink(event:MouseEvent,change:(locale:Locale)=>void,current:{origin:string;pathname:string}=window.location){
  if(event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  const anchor=event.target instanceof Element?event.target.closest<HTMLAnchorElement>('a.locale-control'):null;
  if(!anchor)return;
  const next=localeForLink(anchor.href,current);
  if(!next)return;
  event.preventDefault();event.stopImmediatePropagation();change(next);
}
