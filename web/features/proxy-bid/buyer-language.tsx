'use client';

import {Segmented} from '@beirut-time/ui/foundation';
import {useLocale,useLocaleChange} from '@/shell/locale-context';

export function BuyerLanguageControl() {
  const language=useLocale();
  const change=useLocaleChange();
  return <Segmented label={language==='ar'?'اللغة':'Language'} locale={language}
    value={language} onValueChange={next=>{if((next==='en'||next==='ar')&&next!==language) change(next);}}
    options={[{value:'en',label:<span lang="en">English</span>},{value:'ar',label:<span lang="ar">العربية</span>}]}/>;
}
