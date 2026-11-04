import { getLocale } from '@/shell/locale';
import { direction } from '@/lib/i18n';
import { BRAND_THEME_COLOR } from '@/lib/brand';
export async function GET() {
  const locale = await getLocale();
  return Response.json({ id: '/', name: locale === 'ar' ? 'بيروت تايم' : 'Beirut Time', short_name: locale === 'ar' ? 'بيروت تايم' : 'Beirut Time', start_url: `/${locale}`, scope: '/', lang: locale, dir: direction(locale), display: 'standalone', orientation: 'any', background_color: '#eef2f7', theme_color: BRAND_THEME_COLOR, categories: ['shopping'],
    icons: [{ src: '/icons/bt-192.png', sizes: '192x192', type: 'image/png' }, { src: '/icons/bt-512.png', sizes: '512x512', type: 'image/png' }, { src: '/icons/bt-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' }] }, { headers: { 'Content-Type': 'application/manifest+json' } });
}
