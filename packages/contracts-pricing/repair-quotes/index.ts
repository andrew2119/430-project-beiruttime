export type { AssessedQuote, AssessedLine, Amounts, QuoteContext } from '../quotes/assessed';

export type RepairQuotePage = {
 items: import('../quotes/assessed').AssessedQuote[];
 page: number;
 page_size: 20;
 total: number;
};
