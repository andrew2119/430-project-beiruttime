import { Dependency } from './dependency';
import type { ServiceName, ServiceStatus } from '@/lib/api/types';
// Closed destinations, never a caller-supplied proxy URL. Domain BFF handlers live in modules/.
export const serviceNames: ServiceName[] = ['identity','catalog','auction','pricing','orders','eligibility','trust','communications','service-operations'];
export const dependencies = new Map(serviceNames.map((name, index) => [name, new Dependency(name,
  process.env[`${name.toUpperCase().replaceAll('-', '_')}_API_URL`] ?? `http://127.0.0.1:${8101 + index}`)]));
export async function serviceStatus(name: ServiceName, requestId: string): Promise<ServiceStatus> {
  const response = await dependencies.get(name)!.get('/health/ready', requestId);
  return { service: name, status: response instanceof Response && response.ok ? 'ready' : 'unavailable' };
}
export function requestId(request: Request): string {
  const supplied = request.headers.get('X-Request-ID') ?? '';
  return /^[a-zA-Z0-9_-]{1,64}$/.test(supplied) ? supplied : crypto.randomUUID();
}
export const privateHeaders = (id: string) => ({ 'Cache-Control': 'no-store', 'X-Request-ID': id });
export async function statusResponse(request: Request) {
  const id = requestId(request);
  return Response.json({ services: await Promise.all(serviceNames.map(name => serviceStatus(name, id))), checked_at: new Date().toISOString() },
    { headers: privateHeaders(id) });
}
