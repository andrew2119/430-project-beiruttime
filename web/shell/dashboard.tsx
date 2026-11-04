'use client';
import Link from 'next/link';
import { ArrowRight } from 'lucide-react';
import { navigation } from '@/registry-loader';
import { useAccessContext } from './access-context';
import { useLocale } from './locale-context';
import { permittedEntries } from './navigation';
import { RouteIcon } from './route-icon';
import { PageHeader, PageLayout } from './page-header';
const descriptions:Record<string,{en:string;ar:string}>= {
 watches:{en:'Explore watches from independent sellers.',ar:'تصفح ساعات البائعين المستقلين.'}, search:{en:'Find the right watch, your way.',ar:'اعثر على الساعة المناسبة لك.'}, business:{en:'Meet official dealers and brands.',ar:'تعرّف على التجار والعلامات الرسمية.'}, prices:{en:'Understand prices, fees and exchange rates.',ar:'اطّلع على الأسعار والرسوم وأسعار الصرف.'}, customize:{en:'Request watch options from the brand.',ar:'اطلب خيارات الساعة من العلامة التجارية.'}, services:{en:'Find care from official providers.',ar:'اعثر على خدمات العناية الرسمية.'}, account:{en:'Manage your account and security.',ar:'أدر حسابك وأمانه.'}, settings:{en:'Profile, language and appearance.',ar:'الملف الشخصي واللغة والمظهر.'},
};
export function Dashboard() {
 const locale=useLocale(), access=useAccessContext(), ar=locale==='ar';
 const entries=permittedEntries(navigation,access.roles).filter(n=>n.id!=='home');
 return <PageLayout className="pg-home-page"><PageHeader title={ar?'لوحة التحكم':'Dashboard'} count={ar?'سوق الساعات المستقل في لبنان.':'Lebanon’s independent watch marketplace.'}/><div className="pg-dept-grid">{entries.map(n=><Link key={n.id} href={`/${locale}${n.href}`} className="pg-dept-link"><article className="ui-card pg-dept-card"><span className="pg-dept-card-icon"><RouteIcon id={n.id} href={n.href}/></span><span className="pg-dept-card-copy"><span className="pg-dept-card-title">{n.label[locale]}</span><span className="pg-dept-card-desc">{(descriptions[n.id]??descriptions[n.href.split('/')[1]])?.[locale]??(ar?'افتح هذا القسم من بيروت تايم.':'Open this Beirut Time workspace.')}</span></span><span className="pg-dept-card-go"><ArrowRight aria-hidden="true"/></span></article></Link>)}</div></PageLayout>;
}
