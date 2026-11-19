import { definePageRead } from '@/lib/page-speed/definition';
import { request } from '@/lib/api/client';
import type { SimilarQuery, SimilarResult } from '@contracts/contracts-catalog/similar-watches';
export const similarRead = definePageRead({
  key:(query:SimilarQuery)=>['similar-watches.v1',query.subject_id,query.expected_revision,query.operation_id,query.offset],
  ask:async(signal:AbortSignal,query:SimilarQuery)=>{
    const params=new URLSearchParams({operation_id:query.operation_id,expected_revision:String(query.expected_revision),offset:String(query.offset)});
    const answer=await request<SimilarResult>(`/api/web/v1/catalog/v1/similar-watches/${encodeURIComponent(query.subject_id)}?${params}`,{signal});
    if(answer.schema_version!=='similar-watches.v1'||answer.operation_id!==query.operation_id||answer.subject_id!==query.subject_id||answer.expected_revision!==query.expected_revision||answer.offset!==query.offset) throw new Error('Invalid public result');
    return answer;
  },
  warm:'safe',fresh:0,
});
