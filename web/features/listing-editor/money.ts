import { normalizeDigits } from "@beirut-time/i18n";
export function parseMinor(input: string): number | null {
  const value = normalizeDigits(input).trim();
  if (!/^\d{1,10}(?:\.\d{0,2})?$/.test(value)) return null;
  const [whole, fraction = ""] = value.split(".");
  const amount = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return Number.isSafeInteger(amount) && amount > 0 && amount <= 1e12
    ? amount
    : null;
}
