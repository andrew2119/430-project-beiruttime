import { getLocale } from '@/shell/locale';
import { direction } from '@/lib/i18n';
export async function GET() {
  const locale = await getLocale();
  return Response.json({ id: '/', name: locale === 'ar' ? 'بيروت تايم' : 'Beirut Time', short_name: locale === 'ar' ? 'بيروت تايم' : 'Beirut Time', start_url: `/${locale}`, scope: '/', lang: locale, dir: direction(locale), display: 'standalone', orientation: 'any', background_color: '#f5f2e9', theme_color: '#173c34', categories: ['shopping'],
    icons: [{ src: '/icons/bt-192.png', sizes: '192x192', type: 'image/png' }, { src: '/icons/bt-512.png', sizes: '512x512', type: 'image/png' }, { src: '/icons/bt-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' }] }, { headers: { 'Content-Type': 'application/manifest+json' } });
}
