# Winner, withdrawal and simulated checkout

Owned outcomes: A06, L06, O03. The marketplace never charges real money, sells stock itself or pays a seller through this module.

## Interfaces

- `packages/contracts-orders/allocation/v2.py`: one physical-watch fence, stable service operation lookup, auction-open/first-bid/withdraw/edit and exact allocation. Existing V1 remains available; old auction fences conservatively remain committed.
- `service_app.orders_kernel`: the Orders-local transaction API for custody/jobs. Call inside the existing unit of work; it never commits, makes HTTP calls or grants access. No separate order state/fence/journal is permitted.
- Additive `orders-commitment/v2.1`: Auction-only exact Catalog edit-resolution read, backed by immutable command bindings in the same Orders transaction. A missing receipt stays unknown; only digest-verified replay may backfill old bindings. Generic operation lookup is still producer-private.
- `packages/contracts-orders/payments`: signed simulated card/Whish/OMT attempt and callback bindings. Set a **synthetic, non-production** `BT_SIMULATED_PAYMENT_SECRET` of at least 32 bytes for local proofs. An absent key yields unavailable, never an unsigned paid state.
- `packages/contracts-orders/journal`: exactly balanced immutable held-payment groups. No refund, release or payout API.
- `packages/contracts-auction/closing`: canonical kernel/end-version close, durable winner allocation intent and private own-result read. A missing exact Pricing winner quote stays pending.
- `packages/contracts-catalog/withdrawal`: durable unavailable-before-HTTP withdrawal with current seller/business/revision checks, preserved history and stable original-operation recovery. It borrows Catalog's canonical listing lock and pending-edit guard, so an unresolved published edit cannot be superseded by withdrawal.

Published copies and deterministic positive/negative fixtures live under the corresponding versioned build-contract directories. The Orders HTTP boundary never trusts submitted price/fees; Pricing owns exact schedules and retained snapshots.

## Dashboard tabs

`/checkout` is still registered once by L08. Its L13-owned implementation now receives listing context from the watch action instead of asking users to copy internal IDs. It reads the real listing and availability, creates a Pricing quote, displays exact fee lines, requires explicit acceptance and reserves through `/v1/exact-reservations`. `/checkout/:id` composes the simulated payment panel. `/seller/withdrawals` is a complete additional tab with current personal/business stock, guarded confirmation, durable pending/retry and history. The winner slot is a uniquely named contribution, not another watch page.

All views compose the shared PageLayout/PageHeader, Card, SectionState, Dialog, Select and Segmented controls. Feature styles contain layout only; EN/AR, RTL/LTR references, shared light/dark tokens and the existing phone shell remain authoritative. Current navigation roles are display only; every private endpoint rechecks Identity and record scope.

## Checks

Run lightweight static checks with the local Python environment and the pinned pnpm shim. The browser runner's optional `BT_TOOLS_BIN` defaults to `web/node_modules/.bin`; the publisher's optional `BT_CONTRACTS_DIR` defaults to ignored `tests/lanes/L13/.contracts`. Relative overrides resolve from the repository root; existing `PATH` entries remain available. Heavy checks must use the shared heavy-run wrapper; they must not run concurrently with another heavy job. `run-local.py <orders|auction|catalog>` applies the complete checkout's service-module migration set to new restricted disposable databases on the existing local PostgreSQL. It never migrates a running ordinary domain database.

The tests exercise actual create/reserve/bid/withdraw/payment commands. Deterministic upstream transports are explicitly test-only and do not claim connected cross-service acceptance. The close tests use accepted bid operations, not seeded winners; their deterministic clock covers just-before/exactly-at-end and stale jobs. Payment cases cover exact USD 5,150, all simulated routes, duplicate/racing callbacks, reordered terminal results, wrong bindings/signature, current buyer denial, immutable balance guards, expiry holds and attempt supersession. Withdrawal cases cover pending-before-HTTP, lost response, stable payload replay, denied exception, wrong seller/revision and retained history. Physical first-bid/purchase-versus-withdraw races run against the real Orders row lock.

Connected browser/Docker results, evidence paths and any remaining prerequisites are recorded in `validation.md` after execution. Presentation fixtures alone are not final acceptance.
