# Current buyer activity v2

GET /v1/buyer-workspace/v2?view={view}&cursor={cursor} rechecks current identity,
individual buyer context and source record scope. Views are leading, outbid,
calendar, won, lost, no_sale, unpaid and released. Source Auction endpoints are
GET /v2/my-bids and GET /v2/my-results with the identical view, limit=50 and
opaque cursor. A provider must bind its cursor to actor, organization, filter
and source revision and recheck authority on every page. These source endpoints
describe expected provider behavior.

CurrentActivity has schema_version=2, state, items, total and next_cursor.
Available totals come from the source, including zero. An unavailable Auction
source, including a timeout, returns HTTP 200 with a v2 unavailable page,
no items, null total and null cursor, after verifying current buyer identity.
The buyer can still use the reservation, checkout and inbox reads, which check
access independently. An identity outage returns HTTP 503 before any Auction read. No truncated-page count becomes
a total. The first page must supply a continuation cursor exactly when the
source total exceeds its row count. Invalid, foreign, over-limit or mismatched view rows fail unavailable;
a current denied response denies the whole private read. One bounded source
read has a 600ms deadline. No response includes private ceilings or evidence.

Both source record kinds require is_demo; synthetic rows are visibly labeled.
CurrentBid records contain auction_id, listing_id, buyer_id, status, lifecycle,
current_price_minor, currency=USD, revision, starts_at and ends_at. The source
may include the public listing_title (1 through 240 characters), or omit it
when unavailable. The source filters calendar to scheduled/upcoming and live/ending auctions using server
time. Scheduled rows have status=null and current_price_minor=0. A zero
price records no accepted bids. Live calendar rows use null status when
the buyer has no standing. Leading and outbid views require the corresponding
standing. The end must be after the start and no more than 90 days later.
Source start, end and result timestamps must be UTC date-time strings with
seconds and an explicit UTC offset. Epoch numbers and numeric strings are
invalid. The workspace displays these instants as Beirut civil time.
The released view filters on completed_sale, including lost rows when another
buyer completed the purchase. The won and lost views filter on auction
standing. The unpaid view includes unpaid and unpaid_released financial states.
CurrentResult is the exact results v2 contract. Communications removes buyer_id
from both source record shapes. The result includes the winner's own
financial_state separately from auction standing. Lost and no-sale rows have
a null financial_state. A read never creates transaction authority.

Result rows carry listing_id separately from the physical watch_id. Buyer activity links bind listing_id and auction_id so relisting preserves
access to the selected auction history.

A stale cursor returns HTTP 409 with error code `stale_cursor`. Restart from
the first page without a cursor.

The registered buyer route also accepts GET /v1/buyer-workspace?view={view}
with an optional cursor. Omitting view preserves the original workspace
response for existing clients. With a view, the route uses only its matching
v2 provider. A missing provider yields the unavailable envelope, not a list
filled from unrelated older reads.
A source continuation equal to the requested cursor makes the page unavailable.

Across a complete paging sequence the total stays fixed, auction references
are unique and the continuation ends exactly when the total is reached.
The buyer workspace checks these properties as it follows cursors and offers
a first-page restart when the sequence disagrees.


GET /v1/buyer-workspace?section=reservations returns the v1 reservations
section directly. It verifies the current buyer and reads Orders only.
Use the returned next_cursor as the optional UUID cursor for the next page.
Each request reads at most 100 Orders records and checks ownership again. A
page can contain no displayable records and still have a continuation. The
section parameter cannot be combined with an activity view. An Auction 403 on
the activity read returns code `auction_access_denied` after buyer identity
verification. It denies activity while the Orders reservation read checks
its own access. Authentication failure still closes the private workspace.

The active reservations response includes USD records only. Historic non-USD
records remain with their owning service for restricted read-only access and
reconciliation. The workspace provides no checkout action for those records.
