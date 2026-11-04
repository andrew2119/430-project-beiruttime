import { Suspense } from 'react';
import SearchView from '@/features/discovery/search-view';
import { getLocale } from '@/shell/locale';
import { Skeleton } from '@beirut-time/ui';
import en from '@/features/discovery/en.json';
import ar from '@/features/discovery/ar.json';
export default async function WatchesPage(){const locale=await getLocale();return <Suspense fallback={<Skeleton label={(locale==='ar'?ar:en).loading}/>}><SearchView/></Suspense>;}
