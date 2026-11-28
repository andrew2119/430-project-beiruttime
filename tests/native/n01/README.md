# Native execution interface

Manifest v1 and its schema define ten loopback application processes and nine
private databases. `plan` is pure. `start` and `smoke` require `--capability`;
`start` remains in the foreground while another invocation can inspect or stop
the run. Production web output and pinned dependencies must already exist.

Capability v1 contains `schema_version: 1`, `python`, `postgres_bin`, `batch_id`,
and optional `environment` and `service_environment` maps. It cannot choose the
admission location. Database overrides are forbidden. Private settings require
a service scope and are forbidden for web.

The proposed admission v1 contract is installed at
`/opt/domain-contracts/native-admission-v1.json`, owned by root with no group or
other write permission. Its fields are `schema_version: 1`, `state: "closed"`,
`batch_id`, `expires_at` (epoch seconds), `pid`, `start_ticks` (string), `lock`,
and `lock_identity` (the kernel hexadecimal device pair and decimal inode).
The named process must still hold the exclusive whole-file lock. Absence,
expiry, holder replacement, lock replacement or reopening admission fails
closed. The fixed contract must be supplied and independently verified before
connected execution; local fixtures exercise its proposed shape only.

Ledger v1 retains process session identifiers and kernel start ticks. Shutdown
requires no capability or live admission, so expired admission or a missing
lock holder cannot prevent cleanup of ownership-verified processes. Shutdown
checks session members even after the original leader exits, confirms forced
termination, and records `cleanup-incomplete` when confirmation fails. Private
cluster data and redacted diagnostics remain in the run directory for explicit
later removal; stop does not recursively delete data. Preparation diagnostics
are redacted in memory before being written. Bootstrap initialization disables TCP and uses only the private socket, so no
superuser password is needed. Missing launch identity is retained as
`cleanup-incomplete`; shutdown never infers success or signals an unverified
session. Bootstrap socket trust is removed
and the database restarted with restricted authentication before any application
launch. Runtime environments contain only their own runtime database URL.
