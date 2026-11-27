import { Suspense } from 'react';
import { Skeleton } from '@beirut-time/ui';
import BrandDecisions from '@/features/brand-decisions/view';
import en from '@/features/brand-decisions/en.json';
import ar from '@/features/brand-decisions/ar.json';
import { PageHeader, PageLayout } from '@/shell/page-header';
import { getLocale } from '@/shell/locale';
export async function generateMetadata(){return {title:(await getLocale()==='ar'?ar:en).title};}
export default async function Page(){
 const t=await getLocale()==='ar'?ar:en;
 return <Suspense fallback={<PageLayout><PageHeader title={t.title} count={t.intro}/><Skeleton label={t.loading}/></PageLayout>}><BrandDecisions/></Suspense>;
}
