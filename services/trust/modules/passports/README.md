# Inspection summary module

The route factory is additive and deliberately unregistered. Composition must
supply current identity and a real provider implementing the serialized guard
in CURRENT_V1.md. No permissive provider or accepted inspection is shipped.
The local durable store is a module boundary for focused tests; deployment
storage, module-local migration and relay composition remain with the steward.
No second money journal is created.

Use a durable database filename, injected signing key, pinned issuer key map
and authoritative UTC clock. Never generate a replacement signing key on restart.
Private bindings remain in restricted receipt storage and never in logs or public
responses. Back up receipts and verification keys together. Outbox delivery is
at least once with operation ID deduplication; no relay success is claimed here.

Public summaries always describe a historical inspection. A later modification
does not erase or update a signed record. Inspection scope is a fixed reviewed
claim, never arbitrary source text that could contain a serial or private owner.
