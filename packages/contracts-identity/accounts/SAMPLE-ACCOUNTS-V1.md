# Sample accounts v1

`sample-accounts.v1.json` is the one list of the sample accounts a sample tab may hold.
Identity reads it from the packaged contracts (`bt_contracts.identity.accounts`), and the web kit page imports the same file, so there is no second copy.
Its entries are copied from the demo seed's `accounts.json`, which the seed generates from its own code, leaving out the seed's operator accounts.

Each entry is `{"set", "role", "email", "account_id"}`:

- `set` is one of the seed's two sample sets, `demo` and `click-test`.
- `role` is one of the seed's role names `buyer`, `seller`, `staff` and `rival`, and each role appears once per set.
- `email` is the seed's made-up address for that role and set, `<role>.<set>@example.test`.
- `account_id` is the seed's fixed id for that role and set: the canonical lowercase uuid5 of the public demo key `DEMO-SEED-<SET>-ACCOUNT-<ROLE>` (in capitals) in the seed's namespace, `uuid5(NAMESPACE_URL, "urn:beirut-time:demo-seed:v1")`.

Identity recomputes each entry's id and address from its set and role, so the list can name only the seed's own accounts.
Public registration makes uuid4 ids, so an account it creates can never match an entry, even at a listed address.
Identity refuses the whole list, and with it every sample tab, if any entry breaks these rules, including an entry for the `operator` role.

## What the list controls

- Password-free entry (`POST /v1/demo-entry/sessions` with `{"set", "role", "key"}`) signs a sample tab in only as the account whose id and address both match that set's entry for the role.
- The list alone is not enough: entry also asks the deploy seed's own ownership check, `bt_runtime.demo_seed.account_owner(tx, set, role)`, on the entry's own transaction, and signs in only when it answers `owned`.
  `owned` means the row at the seed's fixed id is the very row the seed inserted, with its address, and the seed's ownership record (`demo_seed_rows`) holds it under that account's demo key.
  Any other answer (`foreign`, `stale`, `missing`, or no seed check in the build) refuses the tab with 409 `sample_account_unavailable`, so an active account that merely matches an entry is never entered.
- The account must also still be `active`.
- A sample tab holds only a link session: a typed sign-in or a registration in a sample tab is refused (403 `slot_unavailable`) for every account, before any account is read.
- A sample tab's refresh, and every Identity check of a link session, ends the session once its account no longer matches an entry of its role.

## The Operator tab is not on the list

The list never names an operator, and the seed's own operator accounts are never a link target.
The Operator tab opens the one existing account that Identity's `BT_DEMO_OPERATOR_EMAIL` setting names, set only in the own settings of the throwaway demo environment the kit runs in, so the repository holds no address of it.
Identity enters it only while all of these hold, and otherwise refuses the Operator tab with 409 `operator_link_unavailable`, with no fallback to any other account:

- The Operator link's fixed cutoff has not passed: the end of Tuesday 1 December 2026 in Beirut, `2026-12-01T22:00:00Z`.
  It is a constant in Identity's code, so no setting can move it later; an earlier `BT_DEMO_ENTRY_UNTIL` still ends the link sooner.
- The account is active.
- The account is none of the deploy seed's accounts: neither its id nor its address is any seed account's fixed id or address, for any set or role, the seed's two operator accounts included.
- The account holds a live platform operator grant.

An Operator link session ends at the cutoff at the latest, and every refresh and Identity check refuses it after that.
Entry never changes that account: no password, grant, membership, address or session-policy change.
The Operator setting is part of the entry activation, with the key fingerprint and the end time, so changing or removing it alone starts a new activation: every link session of the old one ends, sample tabs included.

The kit link names its set (`/sample-tabs#set=click-test&k=...` or `#set=demo&k=...`), so each sample tab it opens holds that set's account; the Operator tab is the same account in both sets.
The list never holds a password, a key, a key fingerprint or a token.
