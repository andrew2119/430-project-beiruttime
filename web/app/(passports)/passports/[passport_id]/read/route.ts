import { dependencies, privateHeaders, requestId } from '@/lib/bff/status';
import { readPassport } from '@/features/passports/read';

export const dynamic = 'force-dynamic';
export async function GET(request: Request, context: {params:Promise<{passport_id:string}>}) {
  const id = requestId(request);
  const headers = privateHeaders(id);
  if (new URL(request.url).search) return Response.json({state:'denied'}, {headers});
  const {passport_id} = await context.params;
  const answer = await readPassport(passport_id, (method,path,document) => dependencies.get('trust')!.request(method,path,id, {
    headers: {'Content-Type':'application/json'},
    body: document ? JSON.stringify(document) : undefined, maxResponseBytes:4096,
  }));
  return Response.json(answer, {headers});
}
