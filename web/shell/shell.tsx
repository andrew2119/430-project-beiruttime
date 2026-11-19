import {navigation,registeredRoutes} from '@/registry-loader';
import type {Locale} from '@/lib/i18n';
import {ShellView} from './shell-view';
// Only plain navigation metadata crosses the boundary; registrations stay server-owned.
export function Shell({children,locale,area='storefront'}:{children:React.ReactNode;locale:Locale;theme:'light'|'dark';area?:'storefront'|'account'|'seller'|'operator'}){
  return <ShellView area={area} navigation={navigation} routes={registeredRoutes} initialLocale={locale}>{children}</ShellView>;
}
