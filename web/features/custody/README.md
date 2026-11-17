# Delivery composition

`CustodyView` is the additive private delivery view for `/deliveries`. Mount it
inside the existing root shell after the page-contract owner registers the route.
No second provider, shell or private cache is introduced. The current shared
page contract admits only its registered internal routes; this module does not
change that registry or create an unregistered public page.

The record read is `custodyRead(order, accessFingerprint)`, keyed by
`custody.v1`, current access and the exact order. The timeline read is
`custodyHistoryRead(order, accessFingerprint, offset)`, keyed separately by
`custody-history.v1`, current access, order and page offset. Both use the shared definition
and mounted-read boundary with open-only intent policy. Shared retained answers
remain visible during refresh; first-load skeletons require no retained answer.
Access changes clear the form, abort pending calls and discard private answers
through the root scope. Refresh errors hide retained private content. Locale is
excluded from form identity and command identity; all unsent fields and exact
pending request bodies stay in memory. No private file picker is introduced.
Unsent receipt fields and confirmation belong to the access-scoped parent and
survive record unmounts during refresh failures. Selecting another order clears
the draft; locale changes do not. Access changes clear the draft.
Pending request bytes belong to the access-scoped delivery parent, survive
record unmounts and read failures, and lock order changes until a definitive
outcome. Retry remains available when private read content is hidden.

The six speed methods are supplied by the common boundary: readiness before
press and intent reads require route registration; retained answers, content
during refresh, first-load-only placeholders and one answer arrival are used by
the view. No per-page size measurement or first-frame/browser verdict is claimed.
The existing root owns first-frame theme, fonts, logical shell direction and
motion/reduced-motion tokens. No image delivery is required for this text record.

The view presents one order with a timeline paged in groups of 25 and a true
server total. The
server adapter owns current proof checks; a local retained answer never approves
handover. Bilingual copy includes denied, pending, empty, unavailable, stale and
incident recovery. The inbox link retains access to transaction support.
