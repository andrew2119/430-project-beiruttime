export type { AssessedQuote, AssessedLine, Amounts, QuoteContext } from '../quotes/assessed';

/** Bounded private read; totals come from the service rather than visible rows. */
export type BrandQuotePage = {
  items: import('../quotes/assessed').AssessedQuote[];
  unavailable: {quote_id: string; code: string; revision?: number; terms_digest?: string}[];
  total: number;
  page: number;
  page_size: number;
};
