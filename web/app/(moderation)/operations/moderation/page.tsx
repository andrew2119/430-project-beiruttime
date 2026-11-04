import OperationsBoundary from '@/features/moderation/session-boundary';
export default async function ModerationPage({searchParams}:{searchParams:Promise<{case?:string}>}) {
  const query=await searchParams;
  const initialCase=query.case&&/^[0-9a-fA-F-]{36}$/.test(query.case)?query.case:undefined;
  return <OperationsBoundary screen="moderation" initialCase={initialCase}/>;
}
