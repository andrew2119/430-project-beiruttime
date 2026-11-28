export function readFailure(error: unknown): 'denied' | 'unavailable' {
  const code = error && typeof error === 'object' && 'code' in error ? error.code : '';
  return code === 'denied' || code === 'unauthorized' ? 'denied' : 'unavailable';
}

export function recoveredRead<T extends string>(previous: T): T | 'empty' {
  return previous === 'unavailable' || previous === 'denied' ? 'empty' : previous;
}
