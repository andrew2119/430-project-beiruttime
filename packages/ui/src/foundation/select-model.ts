import type { SelectOption } from './select-types';
export function filterSelectOptions(options:readonly SelectOption[], query:string, locale:'en'|'ar'):readonly SelectOption[] {
  const needle = query.normalize('NFKC').trim().toLocaleLowerCase(locale);
  return needle ? options.filter(option=>option.label.normalize('NFKC').toLocaleLowerCase(locale).includes(needle)) : options;
}
export function matchingChoice(options:readonly SelectOption[], query:string, after:number, locale:'en'|'ar'):number {
  const needle = query.normalize('NFKC').toLocaleLowerCase(locale);
  for (let offset = 1; offset <= options.length; offset++) {const index = (after+offset+options.length)%options.length; if (!options[index].disabled && options[index].label.normalize('NFKC').toLocaleLowerCase(locale).startsWith(needle)) return index;}
  return -1;
}
