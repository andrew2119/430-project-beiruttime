import { getLocale } from '@/shell/locale';
import { messages } from '@/lib/i18n';
import { Skeleton } from '@/shell/primitives';
export default async function Loading() { return <Skeleton label={messages(await getLocale()).loading} />; }
