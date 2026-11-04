export type ServiceName = 'identity' | 'catalog' | 'auction' | 'pricing' | 'orders' | 'eligibility' | 'trust' | 'communications' | 'service-operations';
export type ServiceStatus = { service: ServiceName; status: 'ready' | 'unavailable' };
export type StatusResponse = { services: ServiceStatus[]; checked_at: string };
export type ErrorEnvelope = { error: { code: string; message: string; request_id: string; details: Record<string, unknown> } };
