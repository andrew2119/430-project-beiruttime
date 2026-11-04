import { notFound } from 'next/navigation';
import OperationsBoundary from '@/features/moderation/session-boundary';
export default async function QueuePage({params}:{params:Promise<{key:string}>}) {
  const {key}=await params;
  if(!['verification','moderation','inspection','disputes','quality'].includes(key))notFound();
  return <OperationsBoundary screen="dashboard" queueId={key}/>;
}
