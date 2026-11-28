export function buyerDateFormatter(locale:'en'|'ar') {
  return new Intl.DateTimeFormat(locale==='ar'?'ar-LB':'en-LB',{
    dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Beirut',
    numberingSystem:locale==='ar'?'arab':'latn',
  });
}
