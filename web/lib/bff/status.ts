import { Dependency } from './dependency';
import type { ServiceName, ServiceStatus } from '@/lib/api/types';
// Closed destinations, never a caller-supplied proxy URL. Domain BFF handlers live in modules/.
export const serviceNames: ServiceName[] = ['identity','catalog','auction','pricing','orders','eligibility','trust','communications','service-operations'];
export const dependencies = new Map(serviceNames.map((name, index) => [name, new Dependency(name,
  process.env[`${name.toUpperCase().replaceAll('-', '_')}_API_URL`] ?? `http://127.0.0.1:${8101 + index}`)]));
// Sample-account entry has its own budget and breaker, so its refusals never make ordinary
// sign-in or principal calls unavailable. Named identity for its route budget.
// It admits one whole sample set at once, because the kit opens one tab per role and the
// class may open them all together; a sample tab retries a busy entry quietly beyond that.
// Identity's 429 for a spent entry budget is its answer, passed through as itself: it is
// neither a 503 nor a failure, so guessing a key can never open this breaker in front of
// the right key.
export const sampleEntryConcurrency = 5;
export const sampleEntry = new Dependency('identity', dependencies.get('identity')!.origin, 1200, sampleEntryConcurrency, 10000, true);
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
