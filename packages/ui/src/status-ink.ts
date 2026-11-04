/** Resolve an ink without changing a status tone's fills, borders or graphic marks. */
export function statusInk(tone: string): string {
  return tone.replaceAll("var(--color-status-green)", "var(--green-ink)");
}
