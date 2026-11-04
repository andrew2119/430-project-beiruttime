export type Money = { amount: string; currency: 'USD' | 'LBP' };
export type Actor = { subject_id: string; organization_id: string | null; session_id: string };
export type Revision = { revision: number };
export type Operation = { id: string; status: 'pending' | 'succeeded' | 'denied' | 'unavailable'; resource_id: string | null; request_id: string };
export type ErrorEnvelope = { error: { code: string; message: string; request_id: string; details: Record<string, unknown> } };
export type EventEnvelope<T extends Record<string, unknown> = Record<string, unknown>> = { specversion: '1.0'; id: string; type: `${string}.v${number}`; source: string; subject: string; time: string; request_id: string; data: T };
