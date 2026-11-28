const localWorkMs = 1200;
// Leave the local work window below the transport's 300 s response header timeout.
const maxRouteBudgetMs = 300_000 - localWorkMs;
const catalogCallMs = 2500;
// The shared runtime database pool caps each command at 3 s
// and unit_of_work caps connection acquisition at 2 s (app/db.py).
const dbCommandMs = 3000;
const transactionAcquireMs = 2000;
// Budget BEGIN and COMMIT alongside the commands in the transaction.
const transactionMs = (commands: number) => transactionAcquireMs + (commands + 2) * dbCommandMs;
// Identity contacts, private review, businesses and membership security each
// read the account, session and grants in a separate principal transaction.
const identityPrincipalMs = transactionMs(3);
// Direct pool reads have no explicit acquisition cutoff. Use the runtime's
// transaction acquisition window as a bounded allowance for these reads.
const pooledReadMs = transactionAcquireMs + dbCommandMs;
// Catalog media/images caps input at 8 million bytes and 20 million pixels
// and encodes three variants. It has no wall-clock cutoff. Allow 3 s for image
// work, rounding up twice the slowest measured whole upload (1272 ms).
const imageWorkMs = 3000;
const colorCallMs = 1500;
const movementIdentityCallMs = 500;
const directoryIdentityCallMs = 500;
const standardCallMs = 1200;
// discovery/service.raw_detail allows 200 ms to acquire the connection and
// discovery/search.detail issues one command.
const discoveryListingReadMs = 200 + dbCommandMs;
// Auction engine.submit reads replay and lot, then the publication watermark.
// Allow another two-command pool read for a pending operation after reconciliation.
// first_bid.prepare adds transactions for inspection (5 commands), staging (9)
// and reconciliation (up to 14, including an expired receipt).
// The final transaction uses 16 fixed commands for locks, reads, state, receipt
// and outbox, plus one insert per bid or maximum. proxy_validation caps the
// result at two bids and 10,000 maxima, with one command per row in engine.submit.
// Auction dependencies allows 1.2 s per peer call, including first-bid fencing.
const auctionBidWorkMs = 10 * standardCallMs + 3 * pooledReadMs + 2 * dbCommandMs
  + transactionMs(5) + transactionMs(9) + transactionMs(14)
  + transactionMs(16 + 2 + 10_000) + localWorkMs;
const auctionBidMs = Math.min(auctionBidWorkMs, maxRouteBudgetMs);
// listings/revisions/routes resume uses up to ten 2.5 s Catalog peer calls.
// Initial load and reconciliation reload each read the edit and listing.
// The five write transactions include an advisory lock each and persist the
// Orders revision (3 commands), mark Auction prepared (2), mark Orders
// started (3), commit listing/history/outbox changes (9, including both
// listing locks and the optional price event), and persist the receipt (5).
const listingEditResumeMs = 10 * catalogCallMs + 2 * (pooledReadMs + dbCommandMs)
  + transactionMs(3) + transactionMs(2) + transactionMs(3) + transactionMs(9) + transactionMs(5) + localWorkMs;
// brand-decisions/routes resume reads the operation, request, and revision on
// one connection. It uses nine Catalog peer calls (two approver checks, three
// authority reads, and two consume calls). Binding persistence takes the
// request lock and writes bindings. Finalization takes the request lock,
// reads the request, revision, and operation, updates status, and adds an
// outbox row. The denial branch uses at most three commands in place of finalization.
const brandDecisionResumeMs = pooledReadMs + 2 * dbCommandMs + 9 * catalogCallMs
  + transactionMs(2) + transactionMs(6) + localWorkMs;
const id = '[A-Za-z0-9_-]{1,200}';
export const publicationPath = new RegExp(`^/v1/seller/listings/${id}/publish$`);

type RouteBudget = readonly [service: string, method: string, path: string | RegExp, milliseconds: number];

export const routeBudgets: readonly RouteBudget[] = [
  // Identity account routes retain the existing credential budget for password hashing.
  ['identity', 'POST', /^\/v1\/accounts\/(login|register|reauthenticate|password|reset|refresh)$/, 8000],
  // accounts/routes me reads the account, session and grants in one transaction.
  ['identity', 'GET', '/v1/accounts/me', identityPrincipalMs + localWorkMs],
  // businesses/routes managed records adds one pool query after live authority.
  ['identity', 'GET', '/v1/businesses/manage/records', identityPrincipalMs + pooledReadMs + localWorkMs],
  // membership/routes checks the business and current staff grant, then reads
  // the roster on the same connection after the principal transaction.
  ['identity', 'GET', '/v1/businesses/:id/memberships', identityPrincipalMs + pooledReadMs + 2 * dbCommandMs + localWorkMs],
  // contacts/routes reads the contact and pending challenge after live authority.
  // The sample-code route reads one challenge after the same principal check.
  ['identity', 'GET', '/v1/contacts', identityPrincipalMs + pooledReadMs + dbCommandMs + localWorkMs],
  ['identity', 'GET', '/v1/contacts/challenges/:id/sample-code', identityPrincipalMs + pooledReadMs + localWorkMs],
  // private-seller/routes mine and private-review/listing_review status load
  // the live account and session, then the application or review in one transaction.
  ['identity', 'GET', '/v1/private-seller/applications/me', transactionMs(3) + localWorkMs],
  ['identity', 'GET', '/v1/listing-reviews/:id', transactionMs(3) + localWorkMs],
  // accounts/routes logout uses one transaction to read the refresh owner,
  // lock the account, revoke the session and insert the audit record.
  ['identity', 'POST', '/v1/accounts/logout', transactionMs(4) + localWorkMs],
  // businesses/routes onboarding takes the operation and account locks,
  // rechecks authority (three commands), checks replay, then writes the
  // business, history, result and two outbox rows.
  ['identity', 'POST', '/v1/businesses', identityPrincipalMs + transactionMs(11) + localWorkMs],
  // businesses/routes and businesses/identity_store.sync_business use the principal
  // transaction and 18 fixed write-transaction commands. Each active member adds
  // a grant insert, and each affected subject adds account and session updates.
  // The command deadline applies per statement, and the service has no aggregate
  // timeout or member limit. Allow the remainder of the transport window for
  // synchronization and use the shared route ceiling as the overall cutoff.
  ['identity', 'PATCH', '/v1/businesses/:id', maxRouteBudgetMs],
  // membership/routes grant uses 20 commands: three locks, three authority
  // reads, business, replay and uniqueness checks, two membership writes,
  // up to five sync_member commands, the result and three outbox rows.
  // Updates replace the uniqueness check with target and locked membership reads.
  ['identity', 'POST', '/v1/memberships', identityPrincipalMs + transactionMs(20) + localWorkMs],
  ['identity', 'PATCH', '/v1/memberships/:id', identityPrincipalMs + transactionMs(21) + localWorkMs],
  // accounts/routes recovery commits IP admission in one pool command.
  // The recovery transaction uses ten commands: advisory lock, receipt table
  // and replay checks, email rate limit, account read, two reset writes,
  // encrypted mail insert, one outbox insert and receipt insert.
  ['identity', 'POST', '/v1/accounts/recovery',
    transactionAcquireMs + dbCommandMs + transactionMs(10) + localWorkMs],
  // contacts/routes challenge locks the operation, checks replay, consumes
  // reauthentication (three commands), reads contact and challenge history,
  // and writes the challenge state, replay result and one outbox row.
  ['identity', 'POST', '/v1/contacts/challenges', identityPrincipalMs + transactionMs(11) + localWorkMs],
  // contacts/routes verify locks the operation, checks account, session,
  // replay, challenge and contact, then writes three state changes, two
  // outbox rows and the replay result.
  ['identity', 'POST', '/v1/contacts/challenges/:id/verify', identityPrincipalMs + transactionMs(12) + localWorkMs],
  // private-review/routes queue and mine read one page after the principal transaction.
  ['identity', 'GET', '/v1/private-reviews', identityPrincipalMs + pooledReadMs + localWorkMs],
  ['identity', 'GET', '/v1/private-reviews/mine', identityPrincipalMs + pooledReadMs + localWorkMs],
  // Detail opens a second transaction for account and session, the review,
  // a three-command reviewer permission recheck, history, application and evidence kinds.
  ['identity', 'GET', '/v1/private-reviews/:id', identityPrincipalMs + transactionMs(9) + localWorkMs],
  // private-review/routes assignment locks the operation and accounts,
  // checks live authority and replay, reads the application twice, checks
  // reviewer eligibility and uniqueness, then writes review and assignment
  // state, history, replay and one outbox row.
  ['identity', 'POST', '/v1/private-reviews', identityPrincipalMs + transactionMs(18) + localWorkMs],
  // Verdict checks the review and application under lock, checks or updates
  // the seller grant and sessions, then writes account, application and
  // review state, history, replay and two outbox rows.
  ['identity', 'POST', '/v1/private-reviews/:id/verdict', identityPrincipalMs + transactionMs(20) + localWorkMs],
  // Reassignment locks the operation and accounts, checks authority, replay
  // and the new reviewer, then updates the review and assignment, history,
  // replay and one outbox row.
  ['identity', 'POST', '/v1/private-reviews/:id/reassign', identityPrincipalMs + transactionMs(15) + localWorkMs],
  // private-seller/routes hashes the bounded application and its evidence.
  // The transaction checks account and session, reads replay and the current
  // application, saves the application and both evidence rows, then writes
  // the replay result, audit and one outbox row.
  ['identity', 'POST', '/v1/private-seller/applications', transactionMs(10) + localWorkMs],
  // private-seller/routes evidence checks account, session, case and assignment,
  // audits access and reads the bytes.
  ['identity', 'GET', '/v1/private-seller/applications/:id/evidence/:evidenceId', transactionMs(6) + localWorkMs],
  // private-review/listing_review.command uses 16 commands for challenge and
  // submission: account and session, review reads and three fence locks,
  // seller authority, operation lock, replay and clock, then proof, audit and receipt.
  // Submission also validates up to 2 MiB / 4 MP of PNG data.
  ['identity', 'POST', '/v1/listing-reviews/:id/challenges', transactionMs(16) + localWorkMs],
  ['identity', 'POST', '/v1/listing-reviews/:id/submissions', imageWorkMs + transactionMs(16) + localWorkMs],
  // Assignment and decision add two three-command require_current checks.
  // Assignment also checks reviewer qualification with one command.
  ['identity', 'POST', '/v1/listing-reviews/:id/assignment', transactionMs(23) + localWorkMs],
  ['identity', 'POST', '/v1/listing-reviews/:id/decision', transactionMs(22) + localWorkMs],
  // Stock decision reads account and session, checks current permission,
  // reads and fences the review, checks reviewer qualification, locks the
  // operation, reads replay and stock matches, then writes clearance, audit and receipt.
  ['identity', 'POST', '/v1/listing-reviews/:id/stock-decision', transactionMs(17) + localWorkMs],
  // The photo read rechecks permission and audits the download.
  ['identity', 'GET', '/v1/listing-reviews/:id/photo', transactionMs(7) + localWorkMs],
  // private-review/security loads account, session and grants. evidence then
  // rechecks those three records and the assignment, reads metadata or file
  // bytes, and writes the access audit.
  ['identity', 'GET', '/v1/private-reviews/:id/evidence', identityPrincipalMs + transactionMs(6) + localWorkMs],
  ['identity', 'GET', '/v1/private-reviews/:id/files/:file', identityPrincipalMs + transactionMs(6) + localWorkMs],

  // Catalog catalog_dependencies gives each peer 2.5 s. Publication retains two
  // authority reads, one quote read, three eligibility checks and one registration.
  ['catalog', 'POST', publicationPath, 7 * catalogCallMs + localWorkMs],
  // media/routes upload resolves Identity, reads ownership, then decodes and
  // encodes media before the write transaction. That transaction has ten
  // commands: advisory lock, owner lock, replay, count, total, asset insert,
  // variant batch, listing update, outbox insert and replay result.
  ['catalog', 'POST', '/v1/seller/listings/:id/media', catalogCallMs + pooledReadMs + imageWorkMs + transactionMs(10) + localWorkMs],
  // media/routes media_list reads ownership and metadata after checking Identity.
  ['catalog', 'GET', '/v1/seller/listings/:id/media', catalogCallMs + 2 * dbCommandMs + localWorkMs],
  // media/routes private_media checks authority, reads the owner and asset,
  // and may fetch the card variant separately. Allow local work for transfer.
  ['catalog', 'GET', '/v1/seller/listings/:id/media/:asset', catalogCallMs + 3 * dbCommandMs + localWorkMs],
  // media/routes gallery runs the same six transaction commands as draft save
  // and verifies the photo set. Removal checks and deletes the selected asset.
  ['catalog', 'PUT', '/v1/seller/listings/:id/gallery', catalogCallMs + transactionMs(7) + localWorkMs],
  ['catalog', 'DELETE', '/v1/seller/listings/:id/media/:asset', catalogCallMs + transactionMs(8) + localWorkMs],
  // media/routes public_photo fetches a stored image variant in one pool read.
  // Allow the local window for transfer of the bounded image response.
  ['catalog', 'GET', '/v1/listings/:id/photos/:asset/:variant', pooledReadMs + localWorkMs],
  // discovery/service.find caps candidate reads, timing, batch resolution and
  // the optional total at 950 ms overall. Allow the local window for response and transport.
  ['catalog', 'GET', '/v1/discovery/watches', 950 + localWorkMs],
  // discovery/service.view and discovery/upstream.read_auction each start
  // an 850 ms composition window after the listing read.
  ['catalog', 'GET', '/v1/discovery/watches/:id', discoveryListingReadMs + 850 + localWorkMs],
  ['catalog', 'GET', '/v1/discovery/watches/:id/auction', discoveryListingReadMs + 850 + localWorkMs],
  // discovery/service.canonical follows the listing read with up to 500 ms
  // for the business eligibility lookup on organization listings.
  ['catalog', 'GET', '/v1/listings/:id', discoveryListingReadMs + 500 + localWorkMs],
  // listings/routes reads the principal and official business, then takes the
  // draft scope lock, checks replay and the optional demo key, inserts the
  // listing, emits one outbox row and stores the receipt.
  ['catalog', 'POST', '/v1/seller/listings', 2 * catalogCallMs + transactionMs(6) + localWorkMs],
  // listings/routes own and get_owned resolve the principal via
  // catalog_dependencies (2.5 s). The collection reads the page and counts
  // in a read-only transaction. Detail reads the listing in one pool command.
  ['catalog', 'GET', '/v1/seller/listings', catalogCallMs + transactionMs(2) + localWorkMs],
  ['catalog', 'GET', '/v1/seller/listings/:id', catalogCallMs + pooledReadMs + localWorkMs],
  // listings/routes save resolves Identity, then takes the advisory and listing
  // locks, checks replay, updates the draft, emits one outbox row and saves replay.
  ['catalog', 'PUT', '/v1/seller/listings/:id', catalogCallMs + transactionMs(6) + localWorkMs],
  // listings/revisions/routes uses the 2.5 s Catalog principal lookup before
  // one pool acquisition. History reads listing, revisions and pending edit.
  // Operation lookup reads the edit and its listing.
  ['catalog', 'GET', '/v1/seller/listings/:id/revisions', catalogCallMs + pooledReadMs + 2 * dbCommandMs + localWorkMs],
  ['catalog', 'GET', '/v1/seller/listing-edit-operations/:id', catalogCallMs + pooledReadMs + dbCommandMs + localWorkMs],
  // Starting a revision adds principal and eligibility calls, the preview and
  // prior edit reads, and a staging transaction with seven commands: the
  // unit_of_work lock, two listing locks, prior edit read, two pending edit
  // checks and the edit insert. It then runs the same resume path.
  ['catalog', 'POST', '/v1/seller/listings/:id/revisions',
    2 * catalogCallMs + pooledReadMs + dbCommandMs + transactionMs(7) + listingEditResumeMs],
  ['catalog', 'POST', '/v1/seller/listing-edit-operations/:id/resume', listingEditResumeMs],
  // listings/routes checks Identity, reads the published listing in one pool
  // query, then checks Orders for a hidden listing's non-owner.
  // catalog_dependencies caps each peer call at 2.5 s.
  ['catalog', 'GET', '/v1/listings/:id/report-subject', 2 * catalogCallMs + pooledReadMs + localWorkMs],
  // configuration/routes publish resolves a principal and active brand, then
  // takes the advisory lock, reads rules and option inputs (five commands),
  // inserts the rule and adds one outbox row.
  ['catalog', 'PUT', '/v1/brands/:id/compatibility/:rule', 2 * catalogCallMs + transactionMs(8) + localWorkMs],
  // configuration/routes rules checks the active brand via catalog_dependencies
  // (2.5 s), then fetches the latest rule revisions in one pool query.
  ['catalog', 'GET', '/v1/brands/:id/compatibility', catalogCallMs + pooledReadMs + localWorkMs],
  // configuration/routes validate resolves the principal and active brand via
  // catalog_dependencies (2.5 s each), with a separate ownership query between them.
  // The validation transaction takes one unit_of_work lock. service_app/configuration
  // adds three locks, two configuration reads, and reads for selections, movement
  // and references. It then reads five option revisions and the matching rule.
  ['catalog', 'POST', '/v1/configurations/:id/validate', 2 * catalogCallMs + pooledReadMs + transactionMs(15) + localWorkMs],
  // request-drafts/submission/routes resolves principal and active brand via
  // catalog_dependencies. One pool acquisition covers draft and replay reads.
  // The write transaction uses 22 commands: operation lock, replay and draft
  // reads, 14 configuration commands, and five request, revision, draft,
  // replay and outbox writes.
  ['catalog', 'POST', '/v1/request-drafts/:id/submit',
    2 * catalogCallMs + pooledReadMs + dbCommandMs + transactionMs(22) + localWorkMs],
  // submission/routes lists at most 100 requests. One acquisition covers the
  // page, optional cursor check and two queries from customization.current
  // per item. The sum of the individual command ceilings exceeds the transport
  // window, so cap the overall route deadline.
  ['catalog', 'GET', '/v1/customization-requests',
    Math.min(2 * catalogCallMs + pooledReadMs + (1 + 2 * 100) * dbCommandMs + localWorkMs, maxRouteBudgetMs)],
  // Detail reads the request and revision, then customization.readable checks
  // the principal and, for business access, the active brand.
  ['catalog', 'GET', '/v1/customization-requests/:id', 2 * catalogCallMs + pooledReadMs + dbCommandMs + localWorkMs],
  // request-drafts/submission/routes history reads the request and current
  // revision, checks the principal and active brand, then acquires another
  // connection to read the revision page.
  ['catalog', 'GET', '/v1/customization-requests/:id/revisions',
    2 * catalogCallMs + 2 * pooledReadMs + dbCommandMs + localWorkMs],
  // request-drafts/submission/routes reference reads the request and revision
  // on one connection. After the principal and brand checks (2.5 s each),
  // it acquires another connection to read the PNG. Allow local time for transfer.
  ['catalog', 'GET', '/v1/customization-requests/:id/references/:reference',
    2 * catalogCallMs + 2 * pooledReadMs + dbCommandMs + localWorkMs],
  // request-drafts/submission/routes operation and brand-decisions/routes
  // decision and operation each read the request, revision and operation on
  // one connection, then check the principal and active brand.
  ['catalog', 'GET', '/v1/customization-operations/:id',
    2 * catalogCallMs + pooledReadMs + 2 * dbCommandMs + localWorkMs],
  ['catalog', 'GET', '/v1/customization-requests/:id/decision',
    2 * catalogCallMs + pooledReadMs + 2 * dbCommandMs + localWorkMs],
  ['catalog', 'GET', '/v1/brand-decision-operations/:id',
    2 * catalogCallMs + pooledReadMs + 2 * dbCommandMs + localWorkMs],
  // brand-decisions/routes readiness reads the request and revision before
  // two approver calls and three authority reads.
  ['catalog', 'GET', '/v1/customization-requests/:id/decision-readiness',
    pooledReadMs + dbCommandMs + 5 * catalogCallMs + localWorkMs],
  // decide adds the request and revision reads, two approver calls, and a
  // staging transaction: advisory lock, request and revision reads, two
  // checks for existing decisions, and intent insertion.
  ['catalog', 'POST', '/v1/customization-requests/:id/decisions',
    pooledReadMs + dbCommandMs + 2 * catalogCallMs + transactionMs(6) + brandDecisionResumeMs],
  ['catalog', 'POST', '/v1/brand-decision-operations/:id/resume', brandDecisionResumeMs],
  // color/routes upload_reference uses the 1.5 s principal deadline from
  // color/dependencies and validates and sanitizes a PNG up to 1 MiB and 1 MP
  // (color/images). Allow local image work separately from the eight commands:
  // two advisory locks, replay, ownership, count, insert, result and outbox.
  ['catalog', 'POST', '/v1/brand-options/configurations/:id/references', colorCallMs + imageWorkMs + transactionMs(8) + localWorkMs],
  // color/routes read_reference resolves the principal (1.5 s in color/dependencies)
  // and fetches the PNG in one database command. Local time covers pool wait and transfer.
  ['catalog', 'GET', '/v1/brand-options/configurations/:id/references/:reference', colorCallMs + dbCommandMs + localWorkMs],
  // color/dependencies.brands uses the 1.5 s directory client, then allows
  // 1.2 s for aggregate verification of the returned page.
  ['catalog', 'GET', '/v1/brand-options/brands', colorCallMs + 1200 + localWorkMs],
  // color/dependencies.brand verifies the directory record and official brand
  // at 1.5 s each. color/routes then reads the brand's options in one pool command.
  ['catalog', 'GET', '/v1/brand-options/brands/:brand', 2 * colorCallMs + pooledReadMs + localWorkMs],
  // color/routes list_configurations resolves the principal (1.5 s in
  // color/dependencies), then reads the buyer's configurations in one pool command.
  ['catalog', 'GET', '/v1/brand-options/configurations', colorCallMs + pooledReadMs + localWorkMs],
  // color/routes get_configuration resolves the principal (1.5 s in
  // color/dependencies), then locks the configuration and reads ownership,
  // selections and references in one transaction.
  ['catalog', 'GET', '/v1/brand-options/configurations/:id', colorCallMs + transactionMs(4) + localWorkMs],

  // color/routes publish and select use three 1.5 s calls from color/dependencies
  // for principal, directory record and official brand. Both transactions include
  // the operation lock, replay read, brand lock, receipt and outbox. Publish also
  // reads revision and capacity before inserting the option. Select adds the
  // configuration lock, configuration and option reads, optional reference check
  // and configuration insert, selection write, revision update and two snapshot reads.
  ['catalog', 'PUT', '/v1/brand-options/brands/:brand/:kind/:option', 3 * colorCallMs + transactionMs(8) + localWorkMs],
  ['catalog', 'PUT', '/v1/brand-options/configurations/:id/:kind', 3 * colorCallMs + transactionMs(14) + localWorkMs],

  // options/movement/dependencies caps each Identity call at 500 ms.
  // routes.options checks the brand and queries the page and count on one connection.
  // Detail checks the brand after looking up the option. Current selection reads
  // the principal before looking up the buyer's selection.
  ['catalog', 'GET', '/v1/options/movement', movementIdentityCallMs + pooledReadMs + dbCommandMs + localWorkMs],
  ['catalog', 'GET', '/v1/options/movement/:id', movementIdentityCallMs + pooledReadMs + localWorkMs],
  ['catalog', 'GET', '/v1/options/movement/selections/current', movementIdentityCallMs + pooledReadMs + localWorkMs],
  // Publication and selection check principal and brand before unit_of_work.
  // Publication takes the advisory lock, reads replay and the locked option,
  // upserts the option and writes the result and outbox. Selection also reads
  // the locked current selection and can archive it before upserting.
  ['catalog', 'PUT', '/v1/options/movement/:id', 2 * movementIdentityCallMs + transactionMs(6) + localWorkMs],
  ['catalog', 'POST', '/v1/options/movement/selections', 2 * movementIdentityCallMs + transactionMs(8) + localWorkMs],

  // request-drafts/dependencies uses 1.2 s each for principal and optional
  // configuration binding. routes.save reads replay before binding, then
  // takes the advisory lock, rechecks replay, writes the draft, audit,
  // outbox and result. Updating additionally locks and reads the draft.
  ['catalog', 'POST', '/v1/request-drafts', 2 * standardCallMs + pooledReadMs + transactionMs(6) + localWorkMs],
  ['catalog', 'PATCH', '/v1/request-drafts/:id', 2 * standardCallMs + pooledReadMs + transactionMs(7) + localWorkMs],
  // request-drafts/routes drafts resolves the principal (1.2 s in
  // request-drafts/dependencies), then uses a read transaction for the
  // optional cursor check, count and page. Allow 2 s for pool acquisition.
  ['catalog', 'GET', '/v1/request-drafts', standardCallMs + transactionMs(3) + localWorkMs],
  // request-drafts/routes detail, future_action and operation each read one
  // ownership-scoped record after the 1.2 s principal lookup.
  ['catalog', 'GET', '/v1/request-drafts/:id', standardCallMs + pooledReadMs + localWorkMs],
  ['catalog', 'POST', '/v1/request-drafts/:id/actions/:action', standardCallMs + pooledReadMs + localWorkMs],
  ['catalog', 'GET', '/v1/request-draft-operations/:id', standardCallMs + pooledReadMs + localWorkMs],
  // Readiness reads the draft, can resolve brand and options in parallel,
  // then can look up the configuration. Each peer phase has the same 1.2 s cap.
  ['catalog', 'GET', '/v1/request-drafts/:id/readiness', 3 * standardCallMs + pooledReadMs + localWorkMs],
  ['catalog', 'GET', '/v1/request-draft-configurations/:id', 2 * standardCallMs + localWorkMs],
  ['catalog', 'GET', '/v1/request-draft-catalogue', 2 * standardCallMs + localWorkMs],

  // rules/routes, rules/public_v2, rules/timing and extension-policy/routes
  // read the lot or page and the database clock on one connection.
  ['auction', 'GET', '/v1/auctions', pooledReadMs + dbCommandMs + localWorkMs],
  ['auction', 'GET', '/v1/auctions/:id', pooledReadMs + dbCommandMs + localWorkMs],
  ['auction', 'GET', '/v2/auctions', pooledReadMs + dbCommandMs + localWorkMs],
  ['auction', 'GET', '/v2/auctions/:id', pooledReadMs + dbCommandMs + localWorkMs],
  ['auction', 'GET', '/v1/auctions/:id/timing', pooledReadMs + dbCommandMs + localWorkMs],
  ['auction', 'GET', '/v2/auctions/:id/policy', pooledReadMs + dbCommandMs + localWorkMs],
  // bid-admission/routes history reads lot, bids and clock in a snapshot.
  // rules/timing listing reads clock, page and matching IDs in a snapshot.
  ['auction', 'GET', '/v1/auctions/:id/history', transactionMs(3) + localWorkMs],
  ['auction', 'GET', '/v1/auction-timing', transactionMs(3) + localWorkMs],
  // Auction dependencies uses 1.2 s per call. Opening checks principal, listing
  // and fence (lookup, write and recheck, including legacy fallback reads).
  // engine.create uses 12 commands: operation lock and replay read, listing
  // lock, edit and lot checks, two clock reads, publication watermark, lot
  // insert, outbox insert, and the receipt read and write.
  ['auction', 'POST', '/v1/auctions', 7 * standardCallMs + transactionMs(12) + localWorkMs],
  // engine.update_rules checks principal, listing and fence (with legacy
  // fallback). Preflight reads the operation and lot on one connection.
  // Its transaction uses the operation, publication and lot locks/checks
  // (six commands), clock read, lot update, outbox insert and two receipt commands.
  ['auction', 'PATCH', '/v1/auctions/:id/rules',
    4 * standardCallMs + pooledReadMs + dbCommandMs + transactionMs(11) + localWorkMs],
  // rules/routes seller_auctions uses the 1.2 s Auction dependencies principal
  // lookup, then reads the database clock and seller's auctions on one connection.
  ['auction', 'GET', '/v1/seller/auctions', standardCallMs + pooledReadMs + dbCommandMs + localWorkMs],
  // Manual and maximum bids share engine.submit and its first-bid flow.
  ['auction', 'POST', '/v1/auctions/:id/bids', auctionBidMs],
  ['auction', 'POST', '/v1/auctions/:id/maximum', auctionBidMs],
  // bid-admission/routes mine uses the 1.2 s Auction dependencies principal
  // lookup, then queries the bids and database clock on one pool connection.
  ['auction', 'GET', '/v1/my-bids', standardCallMs + pooledReadMs + dbCommandMs + localWorkMs],
  // Auction dependencies gives the principal lookup 1.2 s. The v1 reads in
  // prebid-buy-now/routes and find_operation in bid-admission/routes each
  // query the operation once. closing/routes read_mine queries the result once.
  ['auction', 'GET', '/v1/prebid-operations/:key', standardCallMs + pooledReadMs + localWorkMs],
  ['auction', 'GET', '/v1/auctions/:id/my-prebid', standardCallMs + pooledReadMs + localWorkMs],
  ['auction', 'GET', '/v1/auctions/:id/operations/:operation', standardCallMs + pooledReadMs + localWorkMs],
  ['auction', 'GET', '/v1/auction-operations/by-key/:key', standardCallMs + pooledReadMs + localWorkMs],
  // The v2 reads in prebid-buy-now/routes add the database clock query
  // on the same connection after the operation lookup.
  ['auction', 'GET', '/v2/prebid-operations/:key', standardCallMs + pooledReadMs + dbCommandMs + localWorkMs],
  ['auction', 'GET', '/v2/auctions/:id/my-prebid', standardCallMs + pooledReadMs + dbCommandMs + localWorkMs],
  // extension-policy/routes uses the 1.2 s Auction dependencies principal
  // lookup, then reads the lot and database clock on one pool connection.
  ['auction', 'GET', '/v2/seller/auctions/:id/policy', standardCallMs + pooledReadMs + dbCommandMs + localWorkMs],

  // orders_dependencies gives principal, listing and quote calls 1.2 s each.
  // allocation/routes reserve checks replay in the pool before the transaction.
  // Its 14 commands include three from orders_kernel.command (operation lock,
  // replay and receipt), watch lock, clock, order insert, watch update, two
  // audit rows, two reservation event rows, one notice and two payment notice writes.
  ['orders', 'POST', '/v1/reservations', 2 * standardCallMs + pooledReadMs + transactionMs(14) + localWorkMs],
  // allocation/routes orders and operation resolve the principal via
  // orders_dependencies (1.2 s) and each runs one pool query.
  ['orders', 'GET', '/v1/orders', standardCallMs + pooledReadMs + localWorkMs],
  ['orders', 'GET', '/v1/operations/:id', standardCallMs + pooledReadMs + localWorkMs],
  // allocation/routes order and intake_read resolve the principal via
  // orders_dependencies (1.2 s), then use separate pool reads for the order
  // and its audit history or intake records.
  ['orders', 'GET', '/v1/orders/:id', standardCallMs + 2 * pooledReadMs + localWorkMs],
  ['orders', 'GET', '/v1/orders/:id/intake', standardCallMs + 2 * pooledReadMs + localWorkMs],
  // allocation/routes buyer_reservations uses the 1.2 s orders_dependencies
  // principal lookup, then separate pool reads for cursor validation and the page.
  ['orders', 'GET', '/v1/me/reservations', standardCallMs + 2 * pooledReadMs + localWorkMs],
  // allocation/routes transition and intake use the same principal budget. Each
  // reads the order before unit_of_work, then locks it, updates it, writes audit
  // and inserts two outbox rows (allocation/repository event). orders_kernel
  // command and unit_of_work add the advisory lock, replay read and result write.
  // Intake adds a clock read and custody insert.
  ['orders', 'POST', '/v1/orders/:id/transitions', standardCallMs + pooledReadMs + transactionMs(8) + localWorkMs],
  ['orders', 'POST', '/v1/orders/:id/intake', standardCallMs + pooledReadMs + transactionMs(10) + localWorkMs],

  // Communications seller-workspace uses 1.5 s for principal and one parallel
  // wave. Operator-workspace uses 1.2 s for principal and up to two queue reads.
  ['communications', 'GET', '/v1/seller/workspace', 2 * 1500 + localWorkMs],
  ['communications', 'GET', '/v1/operator-workspace/queues', 3 * standardCallMs + localWorkMs],
  ['communications', 'GET', '/v1/operator-workspace/queues/:key', 2 * standardCallMs + localWorkMs],
  // Communications runtime main uses 1.2 s for each call. Readiness resolves
  // principal, reservation and quote, then purchase-readiness/routes reads
  // saved drafts in one pool query.
  ['communications', 'GET', '/v1/buying/readiness', 3 * standardCallMs + pooledReadMs + localWorkMs],
  // Inbox destination checks the target after principal.
  ['communications', 'GET', '/v1/inbox/:id/destination', 2 * standardCallMs + localWorkMs],
  // inbox/routes uses the Communications runtime main principal budget (1.2 s).
  // Listing reads the optional cursor, page, total and unread count on one connection.
  ['communications', 'GET', '/v1/inbox', standardCallMs + pooledReadMs + 3 * dbCommandMs + localWorkMs],
  // inbox/routes preferences reads one row after the runtime principal call.
  ['communications', 'GET', '/v1/inbox/preferences', standardCallMs + pooledReadMs + localWorkMs],
  // Preference writes take the operation lock, read replay and revision, then
  // write the preferences and replay result. Read and clear instead lock and
  // update the notice, store the replay result and insert one outbox row.
  ['communications', 'PUT', '/v1/inbox/preferences', standardCallMs + transactionMs(5) + localWorkMs],
  ['communications', 'POST', '/v1/inbox/:id/read', standardCallMs + transactionMs(6) + localWorkMs],
  ['communications', 'POST', '/v1/inbox/:id/clear', standardCallMs + transactionMs(6) + localWorkMs],

  // purchase-readiness/routes listing and read use the runtime's 1.2 s
  // Identity lookup and one pool read. Send and accept perform the same
  // ownership read before returning the unreleased result.
  ['communications', 'GET', '/v1/buying/drafts', standardCallMs + pooledReadMs + localWorkMs],
  ['communications', 'GET', '/v1/buying/drafts/:id', standardCallMs + pooledReadMs + localWorkMs],
  ['communications', 'POST', '/v1/buying/drafts/:id/send', standardCallMs + pooledReadMs + localWorkMs],
  ['communications', 'POST', '/v1/buying/drafts/:id/accept', standardCallMs + pooledReadMs + localWorkMs],

  // purchase-readiness/routes saves drafts after the runtime principal lookup
  // (1.2 s). The transaction locks the operation, checks replay, writes the
  // draft, result and outbox. Updating also locks and reads the existing draft.
  ['communications', 'POST', '/v1/buying/drafts', standardCallMs + transactionMs(5) + localWorkMs],
  ['communications', 'PUT', '/v1/buying/drafts/:id', standardCallMs + transactionMs(6) + localWorkMs],

  // bid-notices/routes allows 1.2 s for Identity before the list or detail
  // pool query. Detail then allows another 1.2 s for the current auction.
  ['communications', 'GET', '/v1/bid-notices', standardCallMs + pooledReadMs + localWorkMs],
  ['communications', 'GET', '/v1/bid-notices/:id', 2 * standardCallMs + pooledReadMs + localWorkMs],

  // moderation/dependencies allows 1.2 s each for principal, report subject and
  // coverage. moderation/routes report uses seven transaction commands: two
  // advisory locks, replay, rate count, operator selection, case and receipt.
  ['trust', 'POST', '/v1/moderation/reports', 3 * standardCallMs + transactionMs(7) + localWorkMs],
  // moderation/routes queue and detail use the 1.2 s principal lookup in
  // moderation/dependencies. Queue reads page and count on one connection.
  // Detail reads case, audit and delivery on one connection. For reviewers it
  // acquires another connection to read duplicate and velocity signals.
  ['trust', 'GET', '/v1/moderation/cases', standardCallMs + pooledReadMs + dbCommandMs + localWorkMs],
  ['trust', 'GET', '/v1/moderation/cases/:id', standardCallMs + 2 * pooledReadMs + 3 * dbCommandMs + localWorkMs],
  // moderation/routes uses the 1.2 s principal lookup in moderation/dependencies.
  // Each command takes the advisory lock, locks the case, checks replay, updates
  // the case, and stores audit and replay rows. Claim and decision can also check
  // prior appeal reviewers. Decision inserts one outbox row before commit.
  ['trust', 'POST', '/v1/moderation/cases/:id/claim', standardCallMs + transactionMs(7) + localWorkMs],
  ['trust', 'POST', '/v1/moderation/cases/:id/release', standardCallMs + transactionMs(6) + localWorkMs],
  ['trust', 'POST', '/v1/moderation/cases/:id/decisions', standardCallMs + transactionMs(8) + localWorkMs],
  ['trust', 'POST', '/v1/moderation/cases/:id/appeals', standardCallMs + transactionMs(6) + localWorkMs],

  // Eligibility runtime main uses 1.2 s for principal, draft, submitted-request
  // fallback and business. consent/routes checks replay in the pool, then uses
  // eight transaction commands: buyer lock, replay and duplicate checks, consent
  // and evidence inserts, operation result, audit and one outbox row.
  ['eligibility', 'POST', '/v1/consents', 4 * standardCallMs + pooledReadMs + transactionMs(8) + localWorkMs],
  // consent/routes mine uses the runtime's 1.2 s Identity deadline, then
  // reads the page and count on one pool connection.
  ['eligibility', 'GET', '/v1/consents', standardCallMs + pooledReadMs + dbCommandMs + localWorkMs],
  // consent/routes withdraw uses the same principal deadline, then takes the
  // advisory lock, checks replay, locks and updates consent, and writes the
  // operation result, audit and two outbox rows.
  ['eligibility', 'POST', '/v1/consents/:id/withdraw', standardCallMs + transactionMs(8) + localWorkMs],
  // consent/routes evidence uses the runtime principal deadline and a separate
  // 1.2 s cap for the current evidence provider. The transaction also takes
  // the advisory lock, checks assignment, locks consent, audits and reads the file.
  ['eligibility', 'GET', '/v1/consents/:id/evidence/:evidenceId',
    standardCallMs + 1200 + transactionMs(5) + localWorkMs],

  // Pricing runtime main uses 1.2 s per peer call. quotes/routes create
  // resolves the principal, reads replay in the pool and can verify the
  // current listing. The write transaction takes the advisory lock, rechecks
  // replay, inserts the quote and records one outbox event.
  ['pricing', 'POST', '/v1/quotes', 2 * standardCallMs + pooledReadMs + transactionMs(4) + localWorkMs],
  // quotes/routes, quotes/auction_routes, quotes/current_routes and
  // offers/routes resolve the principal and run one ownership-scoped query.
  ['pricing', 'GET', '/v1/quotes', standardCallMs + pooledReadMs + localWorkMs],
  ['pricing', 'GET', '/v1/quotes/:id', standardCallMs + pooledReadMs + localWorkMs],
  // quotes/routes review resolves the principal, reads the quote in the pool
  // and can check the current listing. The write transaction takes the
  // advisory lock, reads the quote, prior review and operation key, inserts
  // the review, updates the quote and inserts one outbox row.
  ['pricing', 'POST', '/v1/quotes/:id/review', 2 * standardCallMs + pooledReadMs + transactionMs(7) + localWorkMs],

  // directory/routes businesses queries the page and count on one connection,
  // then caps aggregate verification at 950 ms.
  ['service-operations', 'GET', '/v1/directory/businesses', pooledReadMs + dbCommandMs + 950 + localWorkMs],
  // Business and provider detail read one profile and verify it using the
  // 500 ms deadline in directory/dependencies. Current choice resolves the
  // principal with the same deadline before reading the buyer's choice.
  ['service-operations', 'GET', '/v1/directory/businesses/:id', pooledReadMs + directoryIdentityCallMs + localWorkMs],
  ['service-operations', 'GET', '/v1/directory/providers/:id', pooledReadMs + directoryIdentityCallMs + localWorkMs],
  ['service-operations', 'GET', '/v1/directory/choices/current', directoryIdentityCallMs + pooledReadMs + localWorkMs],
  // directory/routes publish and choose resolve principal and official business
  // at 500 ms each before unit_of_work. Both take the advisory lock, read replay
  // and the profile, upsert state and write the result and outbox. Choose also
  // reads the buyer's current choice under lock.
  ['service-operations', 'PUT', '/v1/directory/businesses/:id', 2 * directoryIdentityCallMs + transactionMs(6) + localWorkMs],
  ['service-operations', 'POST', '/v1/directory/choices', 2 * directoryIdentityCallMs + transactionMs(7) + localWorkMs],

  // Intake dependencies and access use 1.2 s each for principal, provider
  // and record scope. intake/routes reads page and count on one connection.
  // Detail reads the record once and can also check custody and opening authority.
  ['service-operations', 'GET', '/v1/intake/records', 3 * standardCallMs + pooledReadMs + dbCommandMs + localWorkMs],
  ['service-operations', 'GET', '/v1/intake/records/:id', 5 * standardCallMs + pooledReadMs + localWorkMs],
  // intake/routes save can also check custody. Both transactions take the
  // operation lock, check replay, write intake and audit, enqueue two outbox
  // rows and store the receipt. Create takes an order lock and checks for an
  // existing intake. Update locks and reads the existing intake in one command.
  ['service-operations', 'POST', '/v1/intake/records', 4 * standardCallMs + transactionMs(9) + localWorkMs],
  ['service-operations', 'PUT', '/v1/intake/records/:id', 4 * standardCallMs + transactionMs(8) + localWorkMs],
  // Intake evidence checks principal, provider and record scope. Upload also
  // validates the bounded file payload in evidence and photo. intake/evidence
  // upload takes the operation and intake locks, checks replay, count and
  // duplicate bytes, stores the file, advances the revision, and inserts the
  // audit record, two outbox rows and the receipt.
  // intake/evidence listing reads the order ID and metadata on one connection.
  ['service-operations', 'GET', '/v1/intake/records/:id/evidence', 3 * standardCallMs + pooledReadMs + dbCommandMs + localWorkMs],
  ['service-operations', 'POST', '/v1/intake/records/:id/evidence', 3 * standardCallMs + transactionMs(11) + 2 * localWorkMs],
  // intake/evidence download reads authorization metadata and then file bytes
  // using separate pool acquisitions.
  ['service-operations', 'GET', '/v1/intake/evidence/:id', 3 * standardCallMs + 2 * pooledReadMs + localWorkMs],
];

const matchers = routeBudgets.map(([service, method, path, milliseconds]) => ({
  service, method, milliseconds,
  path: typeof path === 'string' ? new RegExp('^' + path.replace(/:[A-Za-z][A-Za-z0-9_]*/g, '[A-Za-z0-9_.-]{1,200}') + '$') : path,
}));

export function routeBudget(service: string, method: string, pathname: string) {
  return matchers.find(entry => entry.service === service && entry.method === method && entry.path.test(pathname))?.milliseconds;
}
