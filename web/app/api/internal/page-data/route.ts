import { NextRequest, NextResponse } from 'next/server';
import { demoRequest } from '@/internal/page/reads';
import { demoAnswer } from '@/internal/page/demo-data';
/** Public invented review records only. No identity, domain call or mutation. */
export function GET(request:NextRequest) {
  const query = request.nextUrl.searchParams;
  return NextResponse.json(demoAnswer(demoRequest(query.get('data'),query.get('page')),Date.now()),{headers:{'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow'}});
}
