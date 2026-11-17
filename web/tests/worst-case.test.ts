import { describe, expect, it } from 'vitest';
import { CLOCK, COLLECTION_EDGES, IDENTIFIERS, LIMITS, MEDIA, NAMES, REVIEW_ENVIRONMENTS, TEXT, VALUES, reviewWatchDetail, reviewWatches } from './fixtures/worst-case';

describe('shared marketplace review data', () => {
  it('covers long, one-letter, Arabic, non-Latin and joined-emoji names', () => {
    expect(NAMES.long.length).toBeGreaterThan(40);
    expect(NAMES.accountAtLimit).toHaveLength(LIMITS.accountName);
    expect(NAMES.sellerAtLimit).toHaveLength(LIMITS.sellerName);
    expect(NAMES.oneLetter).toHaveLength(1);
    expect(NAMES.arabic).toMatch(/\p{Script=Arabic}/u);
    expect(NAMES.accents).toContain('ễ');
    const segments = new Intl.Segmenter('en', { granularity: 'grapheme' });
    expect([...segments.segment(NAMES.emojiOnly)]).toHaveLength(1);
    expect([...segments.segment(NAMES.emojiFirst)][0].segment).toBe('👩🏽‍💻');
  });
  it('keeps identifiers fictional and text plausibly bounded by the public schema', () => {
    expect(IDENTIFIERS.email).toContain('@');
    expect(IDENTIFIERS.email).toMatch(/\.example\.com$/);
    expect(IDENTIFIERS.email.length).toBeLessThanOrEqual(LIMITS.email);
    expect(new URL(IDENTIFIERS.url).hostname).toBe('example.com');
    expect(TEXT.description).toHaveLength(LIMITS.description);
    expect(TEXT.titleAtLimit).toHaveLength(LIMITS.title);
    expect(TEXT.title.length).toBeLessThanOrEqual(LIMITS.title);
    expect(TEXT.literalMarkup).toContain('<b>');
  });
  it('provides separate empty, one and thousand-row datasets without truncation', () => {
    expect(reviewWatches('empty').items).toEqual([]);
    expect(reviewWatches('one').items).toHaveLength(1);
    const thousand = reviewWatches('thousand');
    expect(thousand.items).toHaveLength(1000);
    expect(new Set(thousand.items.map(item => item.id)).size).toBe(1000);
    expect(thousand.items.at(-1)?.id).toBe('review-watch-1000');
    expect(COLLECTION_EDGES).toEqual([0, 1, 12, 13, 1000]);
  });
  it('mixes every sale state, missing media/prices and text extremes in the first screen', () => {
    const page = reviewWatches('worst');
    expect(new Set(page.items.map(item => item.sale_state)).size).toBe(6);
    expect(page.items.slice(0, 6).map(item => item.title)).toEqual([TEXT.title, TEXT.unbroken, NAMES.oneLetter, TEXT.arabicTitle, NAMES.emojiOnly, TEXT.literalMarkup]);
    expect(page.items.some(item => item.price === null)).toBe(true);
    expect(page.items.some(item => item.thumbnail === null)).toBe(true);
    expect(page.items.some(item => item.thumbnail?.url === MEDIA.broken.url)).toBe(true);
    for (const item of page.items) {
      expect(item.demo).toBe(true);
      expect(item.title.length).toBeLessThanOrEqual(LIMITS.title);
      expect(item.model.length).toBeLessThanOrEqual(LIMITS.model);
    }
  });
  it('isolates calls and retains exact money, timing and environment edge inputs', () => {
    const first = reviewWatches('demo');
    first.items[0].title = 'Changed';
    expect(reviewWatches('demo').items[0].title).not.toBe('Changed');
    expect(reviewWatchDetail().description).toBe(TEXT.description);
    expect(reviewWatchDetail().year).toBeNull();
    expect([VALUES.zero, VALUES.one, VALUES.huge]).toEqual([0, 1, 104_233_918]);
    expect(VALUES.amount).toBe('12345678.90');
    expect(Number.isSafeInteger(VALUES.publicMinorLimit)).toBe(true);
    expect(Number.isNaN(VALUES.invalidNumber)).toBe(true);
    expect(Date.parse(CLOCK.future)).toBeGreaterThan(Date.parse(CLOCK.now));
    expect(REVIEW_ENVIRONMENTS.widths).toContain(320);
    expect(REVIEW_ENVIRONMENTS.locales).toEqual(['en', 'ar']);
    expect(REVIEW_ENVIRONMENTS.themes).toEqual(['light', 'dark']);
    expect(REVIEW_ENVIRONMENTS.zoomPercent).toBe(200);
  });
});
