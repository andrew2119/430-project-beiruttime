import type { Configuration, Kind, Option, SelectionWrite } from '@contracts/contracts-catalog/options';

// An uncertain response is resolved only by an authoritative, exact matching saved intent.
export function matchesAcknowledgedSelection(config: Configuration, kind: Kind, body: SelectionWrite): boolean {
  if (config.revision <= body.expected_revision || config.brand_id !== body.brand_id ||
      config.base_model !== body.base_model || config.caliber !== body.caliber) return false;
  const saved = config.selections.find(selection => selection.kind === kind && selection.component === body.component);
  return !!saved && saved.option_id === body.option_id && saved.option_revision === body.option_revision &&
    JSON.stringify([...saved.reference_ids].sort()) === JSON.stringify([...body.reference_ids].sort());
}

export function hasActivePrice(option: Option): boolean {
  return option.kind !== 'sophistication' || (option.details.currency === 'USD' &&
    Number.isSafeInteger(option.details.price_minor) && option.details.price_minor >= 0);
}
