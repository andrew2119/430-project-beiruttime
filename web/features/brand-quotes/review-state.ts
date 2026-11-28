/** Retained private content is usable only across recoverable read failures. */
export function retainQuoteContent(hasData: boolean, failed: boolean, status?: number): boolean {
  return hasData && (!failed || status === undefined || status >= 500);
}

/** The service projects expiry using its clock and validates every decision. */
export function quoteCanDecide(personal: boolean, policyRevision: number, state: string): boolean {
  return personal && policyRevision === 2 && state === 'issued';
}
