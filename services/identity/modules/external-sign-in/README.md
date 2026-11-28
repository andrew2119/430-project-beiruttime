# External sign-in

`service.py` implements durable single-use challenge admission, private operation lookup and bounded completion against the v1 identity contract. `routes.py` exposes an explicit composition factory. Nothing registers the deterministic provider or changes shared runtime/session ownership.

The identity owner must supply an authoritative scope resolver and a durable `Identity` implementation. It must not derive actor, organization, revision or link proof from a caller's profile. Both completion and lookup recheck current account, exact recipient, membership and receipt scope. Proof consumption, unique external linking and the existing session receipt belong to one identity transaction. Unknown completion is pending and retries retain the original binding. No projection grants permission.

The local store uses an isolated service-private database. Its table is additive and prefixed; it does not read other modules' tables. Deployment into the existing database, expiry cleanup, origin/cookie integration, current-identity composition and durable session delivery require the identity steward. No live endpoint or provider readiness is claimed.

The view is an additive component for the canonical page/shell boundary. It defaults to unavailable and retains the operation during locale changes. Its controller accepts only a supplied private transport, fences identity changes and never persists credentials. Route registration, canonical page registry changes, provider navigation and session attachment remain composition work outside this lease.
