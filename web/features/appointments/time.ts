/** Display the retained instant in Beirut; civil-time admission remains server-owned. */
export function visitTime(instant:string,locale:'en'|'ar') {
  const date = new Date(instant);
  if (!Number.isFinite(date.getTime())) return '—';
  return new Intl.DateTimeFormat(locale === 'ar' ? 'ar-LB' : 'en-LB',{
    timeZone:'Asia/Beirut',numberingSystem:locale === 'ar' ? 'arab' : 'latn',
    year:'numeric',month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',
  }).format(date);
}
