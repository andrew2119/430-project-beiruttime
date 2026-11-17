import { request, requestBlob, ApiError } from '@/lib/api/client';
import { authenticatedRequest, refreshSession } from '@/features/identity/session';
import type { Brand, Catalog, Configuration, Kind, Option, SelectionWrite } from '@contracts/contracts-catalog/options';
export type OfferingWrite = Omit<Option, 'id'|'revision'|'kind'> & {expected_revision:number};
const root = '/api/web/v1/catalog/v1/brand-options';
// Session credentials stay in the Identity SDK's memory; no credential form or persistence.
export const optionsApi = {
  publish: (brand:string, kind:Kind, option:string, body:OfferingWrite, operation:string) => authenticatedRequest<{id:string;revision:number}>(`${root}/brands/${encodeURIComponent(brand)}/${kind}/${encodeURIComponent(option)}`, {
    method:'PUT', headers:{'Content-Type':'application/json','Idempotency-Key':operation}, body:JSON.stringify(body),
  }),
  brands: (signal?: AbortSignal, after?: string|null) => request<{items: Brand[];next_after:string|null}>(`${root}/brands${after?'?after='+encodeURIComponent(after):''}`, {signal}),
  catalog: (brand: string, signal?: AbortSignal) => request<Catalog>(`${root}/brands/${encodeURIComponent(brand)}`, {signal}),
  configurations: (signal?: AbortSignal) => authenticatedRequest<{items: Pick<Configuration, 'id' | 'brand_id' | 'base_model' | 'caliber' | 'revision'>[]}>(`${root}/configurations`, {signal}),
  configuration: (id: string, signal?: AbortSignal) => authenticatedRequest<Configuration>(`${root}/configurations/${encodeURIComponent(id)}`, {signal}),
  save: (id: string, kind: Kind, body: SelectionWrite, key: string) => authenticatedRequest<Configuration>(`${root}/configurations/${id}/${kind}`, {
    method:'PUT', headers:{'Content-Type':'application/json', 'Idempotency-Key':key}, body:JSON.stringify(body),
  }),
  upload: (id: string, file: File, key: string) => authenticatedRequest<{id:string}>(`${root}/configurations/${id}/references`, {
    method:'POST', headers:{'Content-Type':'image/png','Idempotency-Key':key}, body:file,
  }),
  reference: async (id: string, reference: string, accessToken: string, signal?: AbortSignal) => {
    const path=`${root}/configurations/${id}/references/${reference}`;
    const read=(token:string)=>requestBlob(path,{signal,headers:{Authorization:`Bearer ${token}`}});
    try {return await read(accessToken);}
    catch(error) {
      if(!(error instanceof ApiError)||error.status!==401||signal?.aborted)throw error;
      const session=await refreshSession();
      if(!session)throw new ApiError(401,'unauthorized','');
      signal?.throwIfAborted();
      return read(session.access_token);
    }
  },
};
