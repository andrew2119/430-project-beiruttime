import { copy } from './copy';
import type { Command, Result } from '../../../packages/contracts-pricing/minimum-offers/v1';

export function dollarCents(value: string): number | null {
  const digits = value.replace(/[٠-٩]/g, digit => String('٠١٢٣٤٥٦٧٨٩'.indexOf(digit))).replace('٫', '.');
  if (!/^(0|[1-9]\d{0,13})(\.\d{1,2})?$/.test(digits)) return null;
  const [whole, fraction = ''] = digits.split('.');
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
  return Number.isSafeInteger(cents) && cents > 0 ? cents : null;
}
export function dollars(cents: number | null): string {
  return cents === null ? '' : `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, '0')}`;
}
export type Operation = { command: Command; phase: 'pending' | 'saved' | 'denied' | 'stale' };
export function settle(operation: Operation, result: Result): Operation {
  if (result.operation_id !== operation.command.operation_id || result.schema_version !== 1) return operation;
  if (result.state !== 'denied' && (['actor_id', 'organization_id', 'subject_id', 'watch_id', 'expected_revision'] as const)
    .some(key => result[key] !== operation.command[key])) return operation;
  if (result.state === 'saved' && (result.revision !== operation.command.expected_revision + 1 || result.minimum_minor !== operation.command.minimum_minor)) return operation;
  return { ...operation, phase: result.state === 'unavailable' ? 'pending' : result.state };
}

export type FormDraft = { amount: string | null; operation: Operation | null };
export function formReducer(state: FormDraft, action: {type: 'amount'; value: string} | {type: 'operation'; value: Operation | null} | {type: 'reset'}): FormDraft {
  if (action.type === 'reset') return {amount: null, operation: null};
  return action.type === 'amount' ? {...state, amount: action.value} : {...state, operation: action.value};
}
export function localizedForm(draft: FormDraft, locale: 'en' | 'ar') {
  return { draft, text: copy[locale] };
}
