/** Deterministic local contract fixture; route and timezone integration remain deferred. */
const times: Record<string, [string, string]> = {
  '2026-11-16T12:00':['2026-11-16T10:00:00.000Z','+02:00'],
  '2026-06-16T12:00':['2026-06-16T09:00:00.000Z','+03:00'],
  '2026-11-16T19:00':['2026-11-16T17:00:00.000Z','+02:00'],
  '2026-11-17T19:00':['2026-11-17T17:00:00.000Z','+02:00'],
};
export function interpretBeirut(local: string) {
  if (local === '2026-10-24T23:30') throw new Error('ambiguous_beirut_time');
  const value = times[local];
  if (!value) throw new Error('invalid_beirut_time');
  return {local, utc:value[0], offset:value[1], time_zone:'Asia/Beirut'};
}
export function scheduleContract(dependencies: {
  origin: () => boolean;
  forward: (request: Request, context: {params: Promise<{service:string;path:string[]}>}) => Promise<Response>;
}) {
  return async (request: Request) => {
    if (!dependencies.origin()) return new Response(null,{status:403});
    if (!request.headers.has('Authorization')) return new Response(null,{status:401});
    const bytes = await request.arrayBuffer();
    if (bytes.byteLength > 65536) return new Response(null,{status:413});
    try {
      const body = JSON.parse(new TextDecoder().decode(bytes));
      if (body.currency !== 'USD' || 'extension_policy' in body || 'buy_now_minor' in body) throw new Error('invalid');
      const starts = interpretBeirut(body.starts_local), ends = interpretBeirut(body.ends_local);
      if (ends.utc <= starts.utc) throw new Error('invalid');
      if (body.review_only) return Response.json({starts,ends},{headers:{'Cache-Control':'no-store'}});
      if (body.confirmed_starts_at !== starts.utc || body.confirmed_ends_at !== ends.utc) throw new Error('confirmation');
      const forwarded = new Request(request.url,{method:'POST',headers:request.headers,body:JSON.stringify({
        listing_id:body.listing_id,currency:body.currency,opening_minor:body.opening_minor,
        reserve_minor:body.reserve_minor,increment_bands:body.increment_bands,starts_at:starts.utc,ends_at:ends.utc,
      })});
      return dependencies.forward(forwarded,{params:Promise.resolve({service:'auction',path:['v1','auctions']})});
    } catch {return new Response(null,{status:422});}
  };
}
