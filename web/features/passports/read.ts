import type { PassportState, Signed } from '../../../packages/contracts-trust/passports/v1';

export const passportId = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const fields = ['schema_version','passport_id','issuer_id','inspected_at','issued_at','scope','watch_reference','inspected_revision','claim'];
/** Reject unexpected fields before any public rendering or verification request. */
export function signedDocument(value: unknown, id: string): Signed | null {
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, unknown>;
  if (Object.keys(record).sort().join() !== 'key_id,signature,summary' || !record.summary || typeof record.summary !== 'object') return null;
  const summary = record.summary as Record<string, unknown>;
  if (Object.keys(summary).sort().join() !== [...fields].sort().join()) return null;
  if (summary.schema_version !== 'passports.summary.v1' || summary.passport_id !== id || summary.scope !== 'independent_private_sale_inspection' || summary.claim !== 'historical_inspection_summary_only') return null;
  if (![record.key_id,summary.passport_id,summary.issuer_id,summary.watch_reference].every(v => typeof v === 'string' && passportId.test(v))) return null;
  if (typeof record.signature !== 'string' || !/^[A-Za-z0-9_-]{86}$/.test(record.signature)) return null;
  if (typeof summary.inspected_revision !== 'number' || !Number.isInteger(summary.inspected_revision) || summary.inspected_revision < 1 || summary.inspected_revision > 2147483647) return null;
  if (![summary.inspected_at,summary.issued_at].every(v => typeof v === 'string' && /(?:Z|\+00:00)$/.test(v) && Number.isFinite(Date.parse(v)))) return null;
  return value as Signed;
}

export type PublicRequest = (method: 'GET'|'POST', path: string, document?: Signed) => Promise<Response | {kind: 'unavailable'}>;
const recovery = (status: number): PassportState => ({state: status === 404 ? 'empty' : status === 403 || status === 401 ? 'denied' : status === 202 ? 'pending' : status === 422 ? 'invalid' : 'unavailable'});
/** Only the pinned service verifies signatures; a downloaded document alone is insufficient. */
export async function readPassport(id: string, request: PublicRequest): Promise<PassportState> {
  if (!passportId.test(id)) return {state:'empty'};
  try {
    const read = await request('GET', `/public/v1/passports/${id}`);
    if (!(read instanceof Response)) return {state:'unavailable'};
    if (read.status !== 200) return recovery(read.status);
    const document = signedDocument(await read.json(), id);
    if (!document) return {state:'invalid'};
    const checked = await request('POST', '/public/v1/passports/verify', document);
    if (!(checked instanceof Response)) return {state:'unavailable'};
    if (checked.status !== 200) return recovery(checked.status);
    const verified = signedDocument(await checked.json(), id);
    if (!verified || JSON.stringify(verified) !== JSON.stringify(document)) return {state:'invalid'};
    return {state:'verified',document:verified};
  } catch { return {state:'unavailable'}; }
}
