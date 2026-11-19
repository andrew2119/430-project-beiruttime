import type { Comparison, CompareRequest, Facts } from '@contracts/contracts-catalog/comparison';
import { validIdentifier } from './state';
function fail(): never { throw new Error('Comparison unavailable'); }
function object(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return fail();
  const result = value as Record<string, unknown>;
  if (Object.keys(result).length !== keys.length || keys.some(key => !Object.hasOwn(result, key))) return fail();
  return result;
}
function choice(value: unknown, allowed: string[]) { if (typeof value !== 'string' || !allowed.includes(value)) fail(); }
function integer(value: unknown, min: number, max: number) { if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < min || value > max) fail(); }
function text(value: unknown, max = 2000) {
  if (typeof value !== 'string' || !value.length || value.length > max) fail();
}
function bilingual(value: unknown) { const item = object(value, ['en', 'ar']); text(item.en); text(item.ar); }
function list(value: unknown, max: number): unknown[] { if (!Array.isArray(value) || value.length > max) return fail(); return value; }
function facts(value: unknown): Facts {
  const item = object(value, ['title','brand','model','reference','year','condition','component_wear','included','seller_type','modified','modifications','authentication','price_minor','buyer_fee_minor','total_minor','currency','price_basis','economics_revision','demo']);
  for (const key of ['title','brand','model','condition']) bilingual(item[key]);
  if (item.reference !== null) { if (typeof item.reference !== 'string' || item.reference.length > 100) fail(); }
  if (item.year !== null) integer(item.year, 1800, 2100);
  list(item.component_wear, 5).forEach(bilingual);
  const included = list(item.included, 3); included.forEach(value => choice(value, ['box','papers','links']));
  if (new Set(included).size !== included.length) fail();
  choice(item.seller_type, ['private','dealer','brand']);
  choice(item.authentication, ['not_inspected','pending','passed','failed','inconclusive','unavailable']);
  if (item.seller_type !== 'private' && !['not_inspected','unavailable'].includes(String(item.authentication))) fail();
  if (typeof item.modified !== 'boolean' || typeof item.demo !== 'boolean') fail();
  const modifications = list(item.modifications, 20);
  if (item.modified !== Boolean(modifications.length)) fail();
  modifications.forEach(value => { const row = object(value, ['component','provenance','modifier','warranty_issuer']); Object.values(row).forEach(bilingual); });
  choice(item.currency, ['USD']); choice(item.price_basis, ['fixed','auction','offer','unavailable']);
  if (item.economics_revision !== null && (typeof item.economics_revision !== 'string' || !validIdentifier(item.economics_revision))) fail();
  const amounts = [item.price_minor, item.buyer_fee_minor, item.total_minor];
  if (amounts.some(value => value !== null)) {
    amounts.forEach(value => integer(value, 0, 1_000_000_000_000));
    if (!item.economics_revision || item.total_minor !== Number(item.price_minor) + Number(item.buyer_fee_minor)) fail();
  }
  return item as unknown as Facts;
}
export function decodeComparison(value: unknown, operation: string, body: CompareRequest): Comparison {
  const result = object(value, ['schema_version','operation_id','server_time','columns']);
  if (result.schema_version !== 'comparison.v1' || result.operation_id !== operation || typeof result.server_time !== 'string' || !/Z$/.test(result.server_time) || !Number.isFinite(Date.parse(result.server_time))) fail();
  const columns = list(result.columns, 3);
  if (columns.length !== body.selections.length) fail();
  columns.forEach((value, index) => {
    const item = object(value, ['watch_id','expected_revision','state','revision','facts']);
    const selected = body.selections[index];
    if (item.watch_id !== selected.watch_id || item.expected_revision !== selected.expected_revision) fail();
    choice(item.state, ['available','unavailable','pending','denied','stale']);
    if (item.revision !== null) integer(item.revision, 1, 9_000_000_000_000_000);
    if (item.state === 'available') {
      if (item.revision === null || selected.expected_revision !== null && selected.expected_revision !== item.revision) fail();
      facts(item.facts);
    } else if (item.facts !== null) fail();
  });
  return result as unknown as Comparison;
}
