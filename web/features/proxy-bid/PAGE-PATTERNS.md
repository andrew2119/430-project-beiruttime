# Buyer bids and results

The buyer workspace uses the canonical PageFrame, PageHeader, Segmented,
Card, AnimatedList, State, skeletons and controls. One shell owns theme,
direction, safe areas and page arrival. No local overlay or duration table.

Both buyer routes use the shared locale control action. It preserves the
current URL's search and fragment while updating the shared shell, direction
and page labels in place. The same mounted workspace keeps
the chosen view and page across in-place language changes. The maximum form keeps its input, quote, review and exact
pending operation reference in memory. Identity changes remount private form
and activity boundaries. Submitted commands stay in document memory across
route remounts and are partitioned by buyer and listing.
A current read of the original auction must authorize recovery before any
private detail appears. A bound terminal receipt removes the command.
Before sending either command, the page saves its operation and quote bindings
in browser storage, keyed by buyer and listing. A reopened tab in the same
browser profile restores the reference for the original auction, including
after relisting. A receipt lookup can finish without a quote read. To replay a
fee review or bid, the page reads the owner's original quote for the exact
amount. Credentials, access fingerprints and amounts stay out of storage.
If the browser cannot save the reference, the corresponding command stays
unsent. Recovery from another browser profile or after storage is cleared
requires an Auction-owned intent lookup.

The activity read key is [L16, buyer-activity, access fingerprint, view, cursor].
The registered workspace path serves all activity views, with 50 rows and source totals when
available. Reservations and unread notices remain independently recoverable.
Reservations call the Orders-only workspace section. Auction-specific denial
hides activity while those independent reads check their own access.
Every current activity view shows unavailable when its v2 source is absent.
The original workspace response remains separate for existing callers without
a view. Failed identity verification closes the activity gate across tabs and
pages until the current read succeeds.
An Auction-specific denial hides activity rows, totals and record links across
views until a current Auction page succeeds. Reservation and inbox access
checks continue independently during denial and recovery.

The listing-auction read key includes the listing and, when supplied, the
auction ID. An activity link requests the exact auction by ID and checks
its listing against the route. The watch shortcut uses the shared listing descriptor without a recurring
refresh loop. Empty, failed, ended, held and mismatched answers hide the link.
The observed server deadline also hides an expired shortcut locally; only the
server decides bid admission. The link binds the exact auction it displays.
The manual bid slot owns the refresh cadence for the same mounted listing
read, so the shortcut gets current answers without a separate recurring read. The history read binds the displayed
auction and revision. Price, minimum and countdown use server facts.

The buyer views use the root shared read scope. Open-only activity,
reservation and inbox reads require current authorized answers and hide them
on access failure. Public snapshots and history are retained in the shared
cache. Reservation keys include the Orders cursor, with previous and
first-page recovery. AnswerArrival uses the shared recipe once per view
and access scope. Intent warming, first-frame behavior, browser motion and
bundle-size measurement remain owed.

The maximum form uses current v2 authority for read-back and new submissions
when configured. Before v2 activation, the compatibility read permits earlier
receipt recovery. New maximums and stored ceilings require the current provider.
Earlier receipts use the registered auction-scoped lookup after current record
verification. A retained legacy command can repeat its original body and key
to recover a matching receipt or record a terminal denial if it never arrived.
An existing pending receipt remains pending until the canonical transaction
reconciles the original intent and records its terminal decision.
An explicit retry repeats the original v2 body and key for current commands.
V2 read-back requires the displayed revision and rechecks current authority
after five seconds with a three-second request deadline that covers the sequential Identity and Auction gateway calls. A denial hides the private reference
and controls. After identity restoration, request references and recovery actions stay hidden
until the original auction’s private read confirms current access. The typed amount
stays hidden under the same condition. An unavailable
or denied read keeps the original submitted reference in memory.

Route intent warming for /buyer, automatic view-visibility refresh beyond the
existing poll, measured bundle gates, earliest theme/font frame and browser
arrival behavior require shared-shell integration. The local page does not
claim those speed methods as proven. The published contract is additive;
missing v2 providers show unavailable rather than seeded successful activity.

The registered Auction maximum path carries explicitly versioned read,
submission and receipt requests for the buyer. They share the direct v2 route
handlers and cannot fall through to legacy admission. An absent current provider returns unavailable for v2 submission and receipt lookup.
The buyer's historical recovery request carries the original command and key.
It uses the canonical operation lock before provider registration and after
cutover. Explicit recovery can retire an absent command under its original reference.
The installed transaction uses full-step competition and stores only verified
buyer ceilings. Ordinary bids cannot create, raise or reactivate a ceiling.
The consumer handles both classes of outbid notice. Historical receipt
recovery does not reopen old-rule admission.
The buyer route advertises current maximum read-back for bidding only when
the canonical transaction declares v2 and the provider exposes read, submit,
and receipt lookup. A partially installed provider still must pass its access
check for recovery. An authorized historical read returns only the revision.
Fresh maxima require the canonical transaction that can persist the D27
outcome. Unwrapped requests recover earlier receipts by the original key.
Once cutover starts,
fresh unwrapped admission requires the current provider and explicit canonical
activation. Fresh maxima from the buyer form require current v2 access at the
displayed revision. Both bid kinds share the canonical transaction. The stored activity flag and
ceiling provenance stay separate from public standing. Connected verification
of admission, receipt and both durable notice paths remains owed.

Activity validates the complete page and row fields before rendering. A
restored session with the same buyer fingerprint gets a distinct read key;
activity, totals and private actions stay hidden until the current response.
The reservation and unread notice reads then start under that access epoch.

A v2 private ceiling response must match the displayed auction revision before
preview or submission is enabled. The mounted form survives scheduled/live/ended
changes for the same auction and access partition. Closing removes new admission
controls while retaining an uncertain operation reference. A temporary
identity outage hides private content and keeps the same buyer boundary mounted.
Recovery reads the private receipt or explicitly replays the exact original
command against its original auction. An auction selected in activity keeps
its own facts and private form. On reopening a selected auction, a retained
reference can restore the form during an empty, invalid or unavailable public
read. The original auction must pass a current private access check before the
form reveals the reference or enables recovery. Fresh bidding still requires
valid public facts. Requests for other auctions on the same listing appear in
a separate panel with their own access check. The canonical lock resolves any existing
receipt first, then checks current admission for a command that never arrived.
Pending or unavailable responses keep the same reference.
A replacement auction leaves the original recovery in place until its
reference is resolved. A definitive fee-review expiry or stale response
clears that review and permits a fresh preview for a live auction. A transport
failure with no definitive decision preserves the original fee-review reference.
A generic review 404 triggers one bounded, owner-scoped quote read. Pricing’s
explicit missing-quote response ends review recovery, while an unverified 404
leaves the original reference pending. An ended or replaced auction still
shows the terminal review decision, with a continuation to the replacement.

With the current v2 provider, own stored ceiling and active/outbid status remain
readable after close. A first fee-review request that receives a definitive
denial clears the unsent auction intent. An access change hides unresolved
requests. Fee-review recovery checks current
access to the original auction and watch before using the current session to replay
only the fee review with its original reference. A recovered acknowledgement
shows the original auction and review reference, confirms that no bid was sent,
and stays visible under current record access until dismissal or continuation
to the replacement auction. A submitted uncertain bid
retains its own reference for private receipt recovery.

The private workspace includes a watch-reference checkout form. Its watch_id
field forwards the selected reference using checkout’s watch query parameter.
The inbox link shows an accessible unread dot from the canonical inbox read
in the same private page scope. No dot is shown after a failed read or when
the confirmed unread count is zero. These controls disappear with buyer access.

A stale cursor prompts a fresh first-page read in the same activity view.
A lost fee-preview response keeps the same creation reference for the same
amount and auction revision, even after a denied retry. The private input stays
hidden until a fresh access check succeeds. Preview validation requires exactly
15 minutes between the server timestamps. Submission and recovery check the same receipt
bindings against the original reviewed intent before resolving a request.

The maximum form displays the canonical verified-contact threshold in USD
before confirmation. Definitive fee-review failures clear the unsent intent.
Result rows pair auction standing with the winner's own current payment state
and link to the scoped order or auction. Held results link to the auction's
private support conversation.

A fresh bid needs a complete public snapshot with current price, next
minimum, contact verification threshold and UTC timing consistent with its
status. The advertised minimum must match opening or the current price plus
the applicable increment. Invalid admission facts suspend fresh bids while
preserving valid public history and recovery for the original auction and command.
The maximum form also checks whether the current buyer can raise or compete
within the fee preview limit. The fee preview discloses its
simulated source and the 3% buyer fee in both languages.

Pricing decides fee-review expiry on its server clock. Auction checks
current admission under its lock, including expiry after a successful review.
An explicit recovery shows the terminal receipt with its original auction
and request references until the buyer continues. A confirmed end links
to the Won view of the activity workspace, where current source results
determine the action. Buyers can switch to Lost or No sale from there.

The support page opens only the selected auction's conversation under current
buyer access. Its open-only read key includes buyer, access scope, auction and
message cursor. Reading does not create a conversation; opening and sending
are explicit, with separate stable keys. A message's exact draft stays in memory
while its response is uncertain. Denial hides conversation content. Ordinary
message blocks do not govern this transaction conversation. Until an operator
is assigned, it says so and shows the 24-hour follow-up commitment. No external
contact settings or invented inbox destinations are used.
