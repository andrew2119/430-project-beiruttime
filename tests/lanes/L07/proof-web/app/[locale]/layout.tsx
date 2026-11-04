import { cookies } from 'next/headers';
import { Providers } from '@/shell/providers';
import { Shell } from '@/shell/shell';
import '../../../../../../web/app/globals.css';
import '../../../../../../web/features/pricing/styles.css';
import '../../../../../../web/features/inbox/styles.css';
export default async function Layout({children,params}:{children:React.ReactNode;params:Promise<{locale:string}>}) {
 const locale=(await params).locale==='ar'?'ar':'en';const theme=(await cookies()).get('bt-theme')?.value==='dark'?'dark':'light';
 return <html lang={locale} dir={locale==='ar'?'rtl':'ltr'} data-theme={theme}><body><Providers locale={locale}><Shell locale={locale} theme={theme}>{children}</Shell></Providers></body></html>;
}
