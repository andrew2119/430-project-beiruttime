import type { SearchPage, WatchDetail, WatchSummary } from '@contracts/contracts-catalog/discovery';

/** Shared review inputs, never a production data source. Limits are from
 * services/catalog/modules/discovery/models.py (public read models) and
 * services/identity/modules/accounts/routes.py (account names/email).
 * Human names have a 100-character account limit and a separate 160-character
 * public seller limit. These examples test the read boundary, not validation. */
export const LIMITS = { accountName: 100, sellerName: 160, title: 320, model: 160, email: 254, description: 10_000 } as const;
export const NAMES = {
  long: 'Alexandra Marie-Louise de Montmorency-Lichtenstein',
  oneLetter: 'J',
  short: 'Jo',
  arabic: 'نور الهدى عبد الرحمن',
  mixed: 'Maison بيروت للساعات — Rami Haddad',
  accents: 'Nguyễn Thị Ánh Tuyết',
  emojiFirst: '👩🏽‍💻 Priya Nair',
  emojiOnly: '👨‍👩‍👧‍👦',
  spaces: '  Sam   Lee  ',
  accountAtLimit: 'Alexandra Marie-Louise de Montmorency-Lichtenstein and Christopher Alexander Montgomery of Saint Germain'.slice(0, LIMITS.accountName),
  sellerAtLimit: 'Maison des Collectionneurs de Haute Horlogerie de Beyrouth — Alexandra Marie-Louise de Montmorency-Lichtenstein, spécialiste des montres anciennes et contemporaines'.slice(0, LIMITS.sellerName),
} as const;
export const IDENTIFIERS = {
  email: 'bartholomew.fitzgerald@beirut-watch-collectors-association.example.com',
  sharedDomainEmail: 'warranty-and-international-servicing@beirut-watch-collectors-association.example.com',
  url: 'https://example.com/watches/limited-editions/annual-calendar-moonphase?reference=IW503602&condition=unworn',
  file: 'Service history — annual calendar IW503602 — revised 2026-11-15 — signed copy.pdf',
  reference: 'Q1682140-MASTER-ULTRA-THIN-PERPETUAL-PINK-GOLD',
} as const;
export const VALUES = {
  zero: 0, one: 1, grouped: 1_284, huge: 104_233_918,
  publicMinorLimit: 9_000_000_000_000_000,
  amount: '12345678.90', tinyAmount: '0.01', floatingPointTrap: 0.1 + 0.2,
  absent: null, invalidNumber: Number.NaN,
} as const;
export const TEXT = {
  title: 'IWC Portugieser Perpetual Calendar — 18-carat rose gold, complete set with service history and additional leather strap',
  arabicTitle: 'ساعة بتقويم دائم ومراحل القمر مع العلبة والأوراق الأصلية وسجل الصيانة الكامل',
  titleAtLimit: 'Patek Philippe Grand Complications Perpetual Calendar Chronograph in platinum — original dial, full presentation box, certificate of origin, archive extract, documented service invoices, additional alligator strap and original deployant clasp — private collector in Beirut, available for independent inspection by appointment only'.slice(0, LIMITS.title),
  unbroken: 'MasterUltraThinPerpetualCalendarRoseGoldLimitedEdition',
  expandedLabel: 'طلب تخصيص السوار والتحقق من توافر قطع الصيانة الأصلية',
  literalMarkup: '<b>Original dial</b> &amp; **complete set**',
  paragraphs: 'Case inspected under magnification.\nOriginal dial and hands retained; bracelet has all spare links.',
  description: 'A collector-maintained mechanical watch with original papers and a documented service history. '.repeat(110).slice(0, LIMITS.description),
} as const;
export const CLOCK = {
  now: '2026-11-15T12:00:00Z', past: '2023-11-15T12:00:00Z',
  future: '2027-01-01T00:00:00+02:00', boundary: '2026-12-31T23:30:00-08:00', missing: null,
} as const;
export const MEDIA = {
  missing: null,
  broken: { id: 'missing-photo', url: '/demo/watches/review-missing.webp', alt: 'Unavailable watch photograph', alt_ar: 'صورة الساعة غير متاحة' },
  panorama: { width: 4000, height: 200 },
  portrait: { width: 200, height: 4000 },
} as const;
const saleStates: WatchSummary['sale_state'][] = ['available', 'not_started', 'reserved', 'sold', 'ended', 'unavailable'];
const titles = [TEXT.title, TEXT.unbroken, NAMES.oneLetter, TEXT.arabicTitle, NAMES.emojiOnly, TEXT.literalMarkup, TEXT.titleAtLimit];

function watch(index: number, worst: boolean): WatchSummary {
  return {
    id: `review-watch-${index + 1}`, revision: 1,
    title: worst ? titles[index % titles.length] : 'Omega Seamaster Aqua Terra',
    brand: worst && index % 3 === 0 ? 'Manufacture Jaeger-LeCoultre' : 'Omega',
    model: worst && index % 3 === 0 ? 'Master Ultra Thin Perpetual Calendar — boutique edition with original accessories' : 'Aqua Terra',
    location: worst && index % 2 ? 'بيروت — الأشرفية، منطقة المتحف الوطني' : 'Beirut',
    price: worst && index % 3 === 1 ? null : { amount: worst ? VALUES.amount : '4500.00', currency: 'USD' },
    sale_mode: (['fixed', 'auction', 'offer'] as const)[index % 3],
    sale_state: saleStates[index % saleStates.length],
    thumbnail: worst && index % 2 ? { ...MEDIA.broken, id: `missing-${index}` } : null,
    published_at: CLOCK.now, ends_at: index % 3 === 1 ? CLOCK.future : null,
    demo: true,
  };
}
export type ReviewDataMode = 'demo' | 'worst' | 'empty' | 'one' | 'thousand';
/** Recreate independent records for each consumer: reviews cannot mutate a
 * global fixture and accidentally change the next screen's inputs. */
export function reviewWatches(mode: ReviewDataMode): SearchPage {
  const length = mode === 'empty' ? 0 : mode === 'one' ? 1 : mode === 'thousand' ? 1000 : mode === 'worst' ? 12 : 3;
  return { items: Array.from({ length }, (_, index) => watch(index, mode !== 'demo')), next_cursor: null, server_time: CLOCK.now };
}
export function reviewWatchDetail(): WatchDetail {
  return {
    ...watch(0, true), reference: IDENTIFIERS.reference, year: null,
    description: TEXT.description, condition: TEXT.paragraphs, included_items: ['Original box', 'Service papers'],
    modified: false, modified_parts: [], photos: [{ ...MEDIA.broken }],
    seller: { display_name: NAMES.long, kind: 'private', completed_sales: 128, joined_at: CLOCK.past },
    assurance: { kind: 'private_inspection', status: 'pending' },
  };
}
export const COLLECTION_EDGES = [0, 1, 12, 13, 1000] as const;

/** The first shared-component showcase consumes these at the same props/API
 * boundary as ordinary data. Its selector is internal-only, persists in the
 * URL, and swaps instantly; no marketplace route imports this fixture. */
export const REVIEW_ENVIRONMENTS = {
  widths: [320, 360, 390, 1440, 2560], zoomPercent: 200,
  locales: ['en', 'ar'], themes: ['light', 'dark'], directions: ['ltr', 'rtl'],
  states: ['loading', 'error', 'partial', 'no-permission', 'ready'],
} as const;
