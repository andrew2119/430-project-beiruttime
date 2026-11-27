import AssessedPage from '@/features/pricing/assessed-page';
export default async function Page({searchParams}:{searchParams:Promise<Record<string,string|string[]|undefined>>}) {
 const query=await searchParams;const context=new URLSearchParams();
 for(const field of ['source_id','source_revision','assessment_id','assessment_revision']){const value=query[field];if(typeof value==='string'&&value.length<=36)context.set(field,value);}
 return <AssessedPage kind="brand" contextQuery={context.size===4?context.toString():undefined}/>;
}
