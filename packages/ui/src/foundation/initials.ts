let segmenter: Intl.Segmenter | undefined;

/** Whole graphemes, first and last letter-starting words, independent of locale. */
export function initialsOf(name:string): string[] {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const lettered = words.filter(word => /^\p{L}/u.test(word));
  const chosen = lettered.length ? [lettered[0], ...(lettered.length > 1 ? [lettered[lettered.length - 1]] : [])] : words.slice(0, 1);
  const current = segmenter ??= new Intl.Segmenter();
  return chosen.map(word => [...current.segment(word.toUpperCase())][0]?.segment ?? '').filter(Boolean);
}

export function usableImageSource(src:string | null | undefined): string | undefined {
  if (!src) return undefined;
  if (src.startsWith('/') && !src.startsWith('//')) return src;
  try {const url = new URL(src); return url.protocol === 'https:' || (url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) ? url.href : undefined;} catch {return undefined;}
}
