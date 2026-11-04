import type { Metadata } from 'next';
import BrandOptions from '@/features/brand-options/view';
import { getLocale } from '@/shell/locale';
export async function generateMetadata(): Promise<Metadata> {
  return {title:await getLocale()==='ar'?'خصّص ساعتك':'Personalize a watch'};
}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export default async function CustomizePage({searchParams}: {searchParams:Promise<Record<string,string|string[]|undefined>>}) {
  const query=await searchParams;
  const safe=(value:unknown)=>typeof value==='string'&&uuid.test(value)?value:'';
  const identifier=(value:unknown)=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(value)?value:'';
  return <BrandOptions initialBrand={safe(query.brand)} initialConfiguration={safe(query.configuration)} initialBase={identifier(query.base)} initialCaliber={identifier(query.caliber)}/>;
}
