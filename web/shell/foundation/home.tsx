'use client';

import Link from 'next/link';
import { Card } from '@beirut-time/ui/foundation';
import { NavigationIcon, navigationIcons, type NavigationDestination } from '../navigation-icon';
import type { NavEntry } from '@/registry-types';
import { useAccessContext } from '../access-context';
import { useLocale } from '../locale-context';
import { PageFrame, PageHeader, PageBody } from '@/shell/foundation/page';
import { usePageTitle } from './page-title';
import { AnswerArrival } from '@/lib/page-speed/arrival';

const descriptions:Record<string,{en:string;ar:string}>= {
 watches:{en:'Explore watches from independent sellers.',ar:'تصفح ساعات البائعين المستقلين.'}, search:{en:'Find the right watch, your way.',ar:'اعثر على الساعة المناسبة لك.'}, business:{en:'Meet official dealers and brands.',ar:'تعرّف على التجار والعلامات الرسمية.'}, prices:{en:'Understand dollar prices and fees.',ar:'اطّلع على الأسعار بالدولار والرسوم.'}, customize:{en:'Request watch options from the brand.',ar:'اطلب خيارات الساعة من العلامة التجارية.'}, services:{en:'Find care from official providers.',ar:'اعثر على خدمات العناية الرسمية.'}, account:{en:'Manage your account and security.',ar:'أدر حسابك وأمانه.'}, settings:{en:'Profile, language and appearance.',ar:'الملف الشخصي واللغة والمظهر.'},
};
export function HomePage({entries}: {entries: NavEntry[]}) {
  const locale = useLocale(), access = useAccessContext(), ar = locale === 'ar';
  const visible = entries.filter(entry => entry.id !== 'home' && entry.roles.some(role => role === 'public' || access.roles.includes(role)));
  usePageTitle(ar ? 'لوحة التحكم' : 'Dashboard', locale);
  return <PageFrame><PageHeader title={ar ? 'لوحة التحكم' : 'Dashboard'} lead={ar ? 'سوق الساعات المستقل في لبنان.' : 'Lebanon’s independent watch marketplace.'}/>
    <PageBody><AnswerArrival view="home"><div className="bt-page-example-grid" data-bt-glance="">
      {visible.map(entry => <Link prefetch key={entry.id} href={`/${locale}${entry.href}`} className="bt-home-link bt-pressable"><Card>
        <NavigationIcon id={entry.id in navigationIcons ? entry.id as NavigationDestination : 'account'}/><div><h2 className="bt-heading">{entry.label[locale]}</h2>
        <p className="bt-text">{(descriptions[entry.id] ?? descriptions[entry.href.split('/')[1]])?.[locale] ?? (ar ? 'افتح هذا القسم من بيروت تايم.' : 'Open this Beirut Time workspace.')}</p></div>
      </Card></Link>)}
    </div></AnswerArrival></PageBody>
  </PageFrame>;
}
