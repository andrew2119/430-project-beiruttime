import { afterEach, describe, expect, it, vi } from 'vitest';
import { quoteCanDecide, retainQuoteContent } from '../../../../web/features/brand-quotes/review-state';

afterEach(() => vi.restoreAllMocks());

describe('retained quote review', () => {
  it('keeps the same content through refresh failure and recovery', () => {
    expect(retainQuoteContent(true, false)).toBe(true);
    expect(retainQuoteContent(true, true, 503)).toBe(true);
    expect(retainQuoteContent(true, true)).toBe(true);
    expect(retainQuoteContent(true, false)).toBe(true);
  });
  it.each([401, 403, 404, 409])('hides content after an authoritative denial %s', status => {
    expect(retainQuoteContent(true, true, status)).toBe(false);
  });
  it('does not invent content on initial failure', () => {
    expect(retainQuoteContent(false, true, 503)).toBe(false);
  });
  it.each([-86400000, -1, 0, 1, 86400000])('uses server state despite device skew %s', skew => {
    vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-11-05T10:15:00Z') + skew);
    expect(quoteCanDecide(true, 2, 'issued')).toBe(true);
    expect(quoteCanDecide(true, 2, 'expired_return_held')).toBe(false);
    expect(quoteCanDecide(true, 2, 'accepted')).toBe(false);
  });
});
