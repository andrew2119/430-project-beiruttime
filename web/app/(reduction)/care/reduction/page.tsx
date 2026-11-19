import { getLocale } from '@/shell/locale';
import ReductionView from '@/features/reduction/view';
export async function generateMetadata() {return {title:{absolute:await getLocale()==='ar'?'طلب تصغير السوار · بيروت تايم':'Request bracelet reduction · Beirut Time'},robots:{index:false,follow:false}};}
export default function Page() {return <ReductionView/>;}
