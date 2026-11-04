# L07 validation

Checked 4 November 2026 against the frozen foundation extension and published Identity, Catalog, Auction and Orders contracts.

## Passed

- 40 Pricing and 30 Communications tests, including current-source runs in existing images without rebuilding. PostgreSQL proofs use disposable restricted databases/roles.
- Full production web build, TypeScript, ESLint, 48 foundation web tests and 3 lane money/registration tests.
- Real isolated Identity, Pricing and Communications started with Compose. Arabic-digit input produced a retained USD 5,000 + 150 = 5,150 snapshot and separate 250 commission / 4,750 seller net.
- Authenticated durable outbox delivery produced an actual owner-private inbox notice. Read/clear, canonical destination lookup, cross-user denials, persisted draft and direct unreleased payment/send/accept denials were checked against the real APIs.
- Existing acknowledged quote/draft data survived runtime replacement and module migrations.
- 24 authenticated Chrome route observations at verified 1440px desktop and 390px phone widths, English/Arabic and light/dark. No horizontal overflow, minimum 44px action targets, 16px phone inputs and final-action hit testing passed. Sanitized results are in `evidence/browser-matrix.json`.
- Representative desktop light and phone Arabic dark screenshots were visually inspected using the actual headless browser; ignored artifacts remain under `.runtime/`. The final Source selector was subsequently included in the connected geometry matrix.

## Safety assertions

Snapshots are balanced and immutable in PostgreSQL. Proposed/sample quote bases cannot authorize reservations. Listing-bound purchase validation reads the current visible Catalog publication and rejects changed price/revision/currency and equal-or-after expiry, without substituting amounts. Auction's root event receiver remains owned by L05; Inbox uses `/internal/v1/inbox/events` and the authenticated L05 notice bridge. Required bid notices cannot be opted out. No paid order, winning bid, receipt, authentication pass or payout was fabricated.

## Remaining integration gates

The production build currently uses published L01 browser source as an uncommitted overlay; consumer files are not part of this lane's commits. Foundation must land first and be merged from main before this branch is opened for review. The actual reserved-order fee frame also needs L08 to expose its retained `quote_id` and L03 to publish a real demonstration listing reference. Until then, the API reports missing fee binding/unavailable dependencies honestly; it does not display a different quote as the reservation's fee basis. The exact Orders wrapper and binding behavior are covered by versioned transport fixtures.

Jira transitions are held until the plan apply is confirmed complete. Commit and publish scheduling remains enforced by the shared teammate ledger. No hosted validation workflow was added. Physical-device installation, keyboards and assistive technology are distinct from the browser-emulation evidence.
