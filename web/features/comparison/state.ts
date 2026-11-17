import type { CompareRequest, Selection } from '@contracts/contracts-catalog/comparison';
export const validIdentifier = (value: string) => /^[A-Za-z0-9_-]{1,100}$/.test(value);
export function addSelection(current: Selection[], watch_id: string): Selection[] | null {
  if (!validIdentifier(watch_id) || current.length >= 3 || current.some(item => item.watch_id === watch_id)) return null;
  return [...current, { watch_id, expected_revision: null }];
}
export function compareBody(selections: Selection[]): CompareRequest {
  return { schema_version: 'comparison.v1', selections };
}
export function minorDecimal(value: number): string {
  if (!Number.isSafeInteger(value) || value < 0 || value > 1_000_000_000_000) throw new Error('Invalid amount');
  return `${Math.floor(value / 100)}.${String(value % 100).padStart(2, '0')}`;
}
