'use client';
import { usePathname, useSearchParams } from 'next/navigation';
import { Moon, Sun } from 'lucide-react';
import { useTheme } from './theme-provider';
import {messages,type Locale,type Messages} from '@/lib/i18n';
import { Button } from './primitives';
import { localizePath } from './paths';
import {useLocale,useChangeLocale} from './locale-context';
export function Preferences(props:{locale:Locale;theme:'light'|'dark';t:Messages}) {
  const path=usePathname(),search=useSearchParams().toString();
  const locale=useLocale(props.locale),changeLocale=useChangeLocale(),t=messages(locale);
  const {theme:current,cycleTheme}=useTheme();
  const other=locale==='en'?'ar':'en';
  return <div className="preferences">
    <a className="locale-control" href={localizePath(path,other)+(search?`?${search}`:'')} lang={other} hrefLang={other}
      onClick={event=>{if(event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();changeLocale(other);}}>{other==='ar'?'العربية':'English'}</a>
    <Button variant="ghost" size="icon" className="icon-button" onClick={cycleTheme} aria-label={current==='light'?t.dark:t.light}>
      {current==='light'?<Moon aria-hidden="true"/>:<Sun aria-hidden="true"/>}
    </Button>
  </div>;
}
