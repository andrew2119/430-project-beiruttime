Native layout contract v1

Load scripts/native-isolation.py with the standard library import loader.
layout(root, service, lane, profile) returns the manifest described by
scripts/native-isolation.schema.json. It performs no mounts or global writes.
run_service is a separately authorized execution API; the diagnostic CLI never
runs a suite. Both fail closed on missing inputs or isolation capabilities.

The administrator-installed entry point accepts one JSON request on standard
input. Requests have schema_version 1 and operation check or run. A check response
has schema_version 1, capabilities containing every required manifest capability
set to true, and published_contracts_read_only true. A run request includes the
manifest, argv and a clean environment. A successful response must include
schema_version 1, isolation_enforced true and exit_code 0. Failure remains nonzero.
The entry point must independently validate the manifest and source trees before
mounting, reject source races, links and undeclared inputs, and enforce the
requested limits for the complete descendant process tree. Check success cannot
replace enforcement on every run. Responses must exclude credentials and private
evidence. No installed implementation or connected compatibility is asserted.

The backend supplies its verified dependency environment and versioned published
contracts read-only at /opt/domain-contracts. It creates a fresh root, process,
user and private-loopback network namespace and writable temporary storage. Only
the listed source mounts are visible. It supplies restricted database roles in
that private network; host loopback, inherited administrator database URLs and
shared database access are forbidden. Resource scopes and private database
transport require administrator support. If absent, execution must fail.

The service runtime directory provides /app/service_app without source changes.
The L05 cross-runtime profile is a test-only exception: Auction runtime supplies /app while communications modules
remain at /app/modules, Auction modules have a separate /app/auction-modules tree,
and only the communications lane suite is invoked. Ordinary profiles never expose
another service's source. L00, L02 and L04 are explicitly shared lanes; all
other populated lanes require the selected service's own directory, with no
whole-lane fallback when that directory is missing. L10 intentionally supplies an empty read-only baseline,
not the lane's additional proof suite. No test assertions are rewritten.

Communications L03 additionally maps only its seller-workspace module read-only
at /workspace-module, preserving the existing fixture's preferred lookup path.
Other service and lane selections do not receive this compatibility mapping.
Missing or unsafe module input fails layout creation before execution.

Native staging rejects local configuration, signing files, links and special
files (including .pem, .key, .p12 and .pfx), and checks nested Git ignore behavior without creating secret probes.
These checks are limited to the selected manifest inputs. They do not inspect
image build contexts or image contents; both claims are explicitly unsupported.

Deferred proofs: installed sandbox protocol compatibility, real namespace and
resource enforcement, isolated database roles and transport, connected provider
execution, browser, restore, load and physical-device execution. Stub success
proves none of these. No full native execution or release is authorized here.

L11 maps its selected service directory and exactly six parent files read-only:
__init__.py, conftest.py, real_accounts.py, testing_database.py,
service_operations_helpers.py and service_operations_tests_data.py. Missing
shared files fail layout creation. No sibling service directory is exposed.

Run requests include completion_required with the stable service:lane:profile
proof_id and no_skips true. Responses must include completion, described by the
schema completion definition. The backend must collect results for every suite
and descendant invocation, including collection errors, skips and deferred
prerequisites; process exit zero alone is insufficient. A complete result needs
positive collected count, matching passed count, zero skipped/failed/errors and
an empty deferred list. Unavailable database, provider, permission, browser or
device proof must be named in deferred with a reason and state deferred, even
when the underlying test exits zero. Missing or incomplete reports raise
IsolationError, preserving a nonzero outcome for consumers. The backend owns
result collection; no parsing of success from console text is permitted.
