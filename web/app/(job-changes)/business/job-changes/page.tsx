import { Suspense } from 'react';
import { Skeleton } from '@beirut-time/ui';
import JobChanges from '@/features/job-changes/view';
import { getLocale } from '@/shell/locale';
import en from '@/features/job-changes/en.json';
import ar from '@/features/job-changes/ar.json';
export async function generateMetadata(){return {title:(await getLocale()==='ar'?ar:en).title};}
export default function Page(){return <Suspense fallback={<Skeleton/>}><JobChanges/></Suspense>;}
