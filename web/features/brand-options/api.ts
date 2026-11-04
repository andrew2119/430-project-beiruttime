import { request, requestBlob, ApiError } from '@/lib/api/client';
import { authenticatedRequest, refreshSession } from '@/features/identity/session';
import type { Brand, Catalog, Configuration, Kind, SelectionWrite } from '@contracts/contracts-catalog/options';
const root = '/api/web/v1/catalog/v1/brand-options';
// Session credentials stay in the Identity SDK's memory; no credential form or persistence.
export const optionsApi = {
  brands: (signal?: AbortSignal) => request<{items: Brand[]}>(`${root}/brands`, {signal}),
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
