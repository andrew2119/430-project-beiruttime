import { serviceNames, serviceStatus, requestId, privateHeaders } from '@/lib/bff/status';
import type { ServiceName } from '@/lib/api/types';
export const dynamic = 'force-dynamic';
export async function GET(request: Request, context: { params: Promise<{ service: string }> }) {
  const { service } = await context.params;
  const id = requestId(request);
  if (!serviceNames.includes(service as ServiceName)) return Response.json({ error: { code: 'not_found', message: 'Resource not found.', request_id: id, details: {} } },
    { status: 404, headers: privateHeaders(id) });
  const result = await serviceStatus(service as ServiceName, id);
  if(result.status==='unavailable') return Response.json({error:{code:'unavailable',message:'Service is temporarily unavailable.',request_id:id,details:{service}}},{status:503,headers:privateHeaders(id)});
  return Response.json(result, { headers: privateHeaders(id) });
}
