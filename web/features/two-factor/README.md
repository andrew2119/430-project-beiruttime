# Account security composition

`SecurityView` uses the canonical page geometry and fields. Its connected form requires the root shared page-read scope and the current identity provider. The route remains unavailable until its steward composes those prerequisites and enables `connected`; it must never create a second shell or provider. `SensitiveProofForm` accepts the protected operation's exact current scope and returns only a scoped proof. Its consumer still needs authoritative capability checks and durable consumption. A proof-ready message is not an accepted payout change or review.

Status uses `['two-factor-status-v1', access_fingerprint]`, with no secret material in the answer. The read is open-only with zero freshness. The transport projects only schema, revision and status into shared memory. Factor secrets, codes, passwords, exact pending commands and their results live only in the mounted form. Access changes replace the form; locale changes retain it. Uncertain mutations retain their immutable command for retries and disable editing until resolved. Code lists are finite ten-item private results, not paginated public data.

The six shared delivery methods apply as follows:

- Route readiness belongs to the root destination owner; this feature adds no private prefetch engine.
- Intent data warming is disabled for security reads. Merely hovering must not request private factor state.
- Kept status answers use the root access-partitioned memory; secrets are never retained there.
- Refresh keeps the existing answer visible while requesting current status. It grants no command authority.
- Loading placeholders appear only before the first status answer. Unavailable reads expose a retry action.
- The first server frame contains the canonical header and honest unavailable state until composition is enabled. No feature arrival animation or first-frame performance claim is added.

The owned `/account/security` page mounts `SecurityView` with its default unavailable state and declares its static, read-free delivery contract in this folder. The shared shell composition owner must provide the canonical root scope and current identity provider before enabling the connected form. At that point the delivery contract must declare its shared status read. Recovery support currently has no connected interface; the visible recovery state says no reset was submitted. Do not replace that state with a presumed successful request.
