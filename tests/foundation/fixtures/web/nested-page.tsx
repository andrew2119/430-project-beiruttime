import { headers } from 'next/headers';
import { hasRoute } from '@/registry-loader';
// Production-build routing fixture only; not an implemented marketplace screen.
export default async function NestedRouteProof() {
  const requestHeaders = await headers();
  return <section data-registered={String(hasRoute(requestHeaders.get('x-bt-path') ?? ''))} data-proxy-proof="nested" data-locale={requestHeaders.get('x-bt-locale')} data-path={requestHeaders.get('x-bt-path')}><h1>Foundation nested-route proof</h1></section>;
}
