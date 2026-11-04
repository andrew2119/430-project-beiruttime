import type { Registration } from '../registry-types';
export default {
  lane: 'L00', namespace: 'foundation',
  routes: [{ path: '/', roles: ['public'], area: 'storefront' }, {path:'/about',roles:['public'],area:'storefront'}, {path:'/settings',roles:['public'],area:'account'}],
  navigation: [
    { id: 'home', href: '', label: { en: 'Dashboard', ar: 'لوحة التحكم' }, order: 0, area: 'storefront', bottom: true, roles: ['public'] },
    { id: 'settings', href: '/settings', label: { en: 'Settings', ar: 'الإعدادات' }, order: 99, area: 'account', roles: ['public'] },
    { id: 'about', href: '/about', label: { en: 'Our perspective', ar: 'رؤيتنا' }, order: 80, area: 'storefront', roles: ['public'] },
  ],
  dictionaries: { en: {}, ar: {} },
} satisfies Registration;
