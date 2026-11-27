'use client';
import { Button, formatNumber } from '@beirut-time/ui/foundation';
import { useLocale } from '@/shell/locale-context';
import type { Page } from '@contracts/contracts-identity/businesses/workspace_v2';
import { businessRequest } from './transport';
import { useCopy } from './components';
import { ApiError } from '@/lib/api/client';
export async function pagedRequest<T>(path:string,page:number,authenticated=true,signal?:AbortSignal):Promise<Page<T>> {
  const result=await businessRequest<Page<T>>(`${path}${path.includes('?')?'&':'?'}page=${page}&page_size=25`,signal ? {signal} : {},authenticated);
  if (!Array.isArray(result.items) || result.items.length>25 || !Number.isSafeInteger(result.total) || result.total<0
      || result.page!==page || result.page_size!==25 || result.items.length>result.total)
    throw new ApiError(503,'unavailable','');
  return result;
}
export function PageControls({answer,change,disabled=false}: {answer:Pick<Page<unknown>,'page'|'page_size'|'total'>;change:(page:number)=>void;disabled?:boolean}) {
  const t=useCopy(),locale=useLocale();
  return <div><p>{t.serverTotal}: {formatNumber(answer.total,locale)}</p>
    <Button disabled={disabled || answer.page<=1} onClick={()=>change(answer.page-1)}>{t.previous}</Button>
    <Button disabled={disabled || answer.page*answer.page_size>=answer.total} onClick={()=>change(answer.page+1)}>{t.next}</Button>
  </div>;
}
