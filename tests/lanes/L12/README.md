# Reserve and anti-sniping policy

The policy module supplies pure accepted-bid extension and public-price reserve predicates to the published canonical Auction kernel. It never creates a separate engine or close transaction. A qualifying admitted manual/proxy command extends the current deadline by 120 seconds once, even if it produces two public bid rows. Replay and private-cap-only changes do not extend. The exact deadline is closed according to server time.

Current sellers configure extension and the optional canonical prebid price before the first accepted bid or competing mode. Public policy never includes the reserve amount, private cap or buyer. Configuration, operation receipt and parked outbox fact commit together; no unsupported relay receiver is enabled.

The seller studio and registered public policy dashboard use the shared Creator Pipeline shell/primitives and EN/AR copy. Current canonical mode is an explicit v2 projection; only missing v2 routes use rolling-upgrade v1 fallback. Seller summaries share the policy panel's current projection.

## Checks

Run heavy checks only through bt-heavy.sh. check-service.py reuses the current Auction test image with read-only source/contract mounts and isolated restricted databases. test_policy.py covers boundaries, permissions, stale revision, replay, frozen state and reserve privacy; test_extension_engine.py exercises actual late manual/proxy commands against strict upstream fixtures. Source R0 discovery is checked separately under tests/foundation/test_extension.py. The owned Compose/browser scripts cover public and guarded seller tabs in both languages/themes at desktop and actual 390px. They stop all owned processes and do not claim connected payment acceptance.

Published provider source may be copied locally for validation but never committed here. Kernel/mode ownership remains in its provider; the single physical-watch authority remains Orders. Auction policy v1 freezes the additive prebid and quote-binding shapes for the next command implementation.
