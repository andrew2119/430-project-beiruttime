# Canonical inbox composition

CanonicalInboxPage is mounted through the original feature entry point inside the existing
root shell and query cache. It uses access-scoped reads without adding a provider.
Do not add a feature-level query provider, shell or notification outlet.

The notice read key is `inbox, access fingerprint, notices, cursor`; preferences
use `inbox, access fingerprint, preferences`. Both calls pass the same access
fingerprint to the authenticated request boundary. The root cache and authenticated request boundary own
retention, cancellation and identity clearing. Language does not enter either
key, remount the view or reset cursor history and pending-operation references.

Reads are open-only. The shared shell owns intent warming, route registration,
retained-answer lifetimes, first-frame paint and arrival timing. There is no
feature-owned preload, second cache or page-size exemption. The mounted view
keeps the current answer through refresh; first reads use shared skeletons.
Mounted reads use the shared usePageRead boundary. Shared shell adoption of the
feature delivery contract and arrival timing remain deferred. No first-frame or warming proof is claimed.
Each server page has at most twenty notices. Server total and unread count are
separate from the number of rendered rows. Paging changes only the exact cursor.

Read and clear are separate commands. Neither changes payment availability or
the underlying transaction. Every retry retains its original key, body and
revision. Opening resolves the current destination through its owning service;
a notice is never permission to act. Required categories ignore optional quote
preferences, and device-delivery refusal does not remove inbox availability.

An unresolved action blocks other notice commands and navigation between pages.
Its retry retains the exact closure, request body and operation key until success.

A definitive refusal releases the unresolved command and refreshes current state.
A new action uses the current revision; uncertain delivery retains the original reference.
