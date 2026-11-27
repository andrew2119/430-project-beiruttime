export function isTestKey(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  const size = Array.from(value).length;
  const edgeSpace = /^(?:\p{White_Space})|(?:\p{White_Space})$/u;
  const invalid = /[\p{Cc}\p{Cs}]/u;
  return size >= 1 && size <= 120 && !edgeSpace.test(value) && !invalid.test(value);
}

export function validTestKeys(value: readonly string[]): boolean {
  return Array.isArray(value) && value.length >= 1 && value.length <= 30
    && value.every(isTestKey) && new Set(value).size === value.length;
}
