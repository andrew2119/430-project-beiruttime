# Eligibility decisions

Additive composition leaves: `routes.py:router` and `migrations/L19_0001_decisions.sql`. Registration remains with the runtime steward: the present registration parser accepts only earlier lane identifiers. Do not register a second service or change applied migrations.

The adapter locks the consent row in the same transaction as review, prepare, consume and revoke. The existing withdrawal update takes that row lock before becoming pending. All paths derive effectiveness from current consent, never stored grant status alone. A successful consume records authorization once, not evidence of production, payment or completion. Integrating consumers must atomically bind their command to that consume receipt and the producer invalidation fence.

Decision state and command receipts commit together. Bounded current-provider outages create no successful receipt. Corrections append immutable history; subsequent review supersedes current authority without deleting previous verdicts. Private explanations stay in the service database and are excluded from responses.
