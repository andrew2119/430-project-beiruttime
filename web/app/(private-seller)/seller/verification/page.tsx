import { getLocale } from '@/shell/locale';
export async function generateMetadata() { return { title: await getLocale() === 'ar' ? 'التحقق من البائع الفردي' : 'Private seller verification' }; }
export { default } from '@/features/identity/seller-view';
