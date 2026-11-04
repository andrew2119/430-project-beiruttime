// Exact V1 minor-unit rendering: never divide a safe integer through binary floating point.
export function formatQuotedMoney(minor:number,currency:'USD'|'LBP',locale:'en'|'ar'){
  if(!Number.isSafeInteger(minor)||minor<0)throw new RangeError('Invalid quoted minor units');
  const value=BigInt(minor),whole=value/100n,fraction=(value%100n).toString().padStart(2,'0');
  const numberingSystem=locale==='ar'?'arab':'latn';
  const digits=new Intl.NumberFormat(locale,{useGrouping:false,numberingSystem});
  const localizedFraction=[...fraction].map(digit=>digits.format(Number(digit))).join('');
  return new Intl.NumberFormat(locale,{style:'currency',currency,numberingSystem,minimumFractionDigits:2,maximumFractionDigits:2})
    .formatToParts(whole).map(part=>part.type==='fraction'?localizedFraction:part.value).join('');
}
