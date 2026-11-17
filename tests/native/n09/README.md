# Native browser contract, version 1

Offline dispatch: `node scripts/native-browser.mjs --plan`.
Connected dispatch, only after separate execution authorization:
`node scripts/native-browser.mjs --origin ORIGIN --run-dir DIR --matrix scripts/native-browser-matrix.json --require-all`.
Every connected invocation requires complete evidence; omitting the final flag does not weaken that rule.

Set `BT_NATIVE_BROWSER` to the explicitly selected installed Linux executable.
No browser download or sandbox bypass is permitted. The adapter must reuse the
current repository browser interface, with isolated session state and bounded
calls, and must reject unsupported executable selection rather than fall back.
The default null adapter leaves connected execution unavailable.

A repository-relative matrix `adapter` module exports `open(config)` returning
`observe(request)`, `screenshot(path)` and `close()`. Config includes origin,
explicit browserPath, exact cell metrics, sandbox true, download false and
reducedMotion reduce. Config and observation requests include an AbortSignal; screenshot receives it
as a second argument. Adapters must stop work when that signal aborts, before
close completes. Late startup sessions are explicitly closed by the dispatcher.
Each adapter call, screenshot read/validation and physical record read has a
15-second deadline. Startup cancellation awaits late-session cleanup within a
separate deadline. Cleanup failure or timeout records a required failure and
prevents opening further cells; a session arriving later still receives close. The adapter must cancel its pending
work on failure and release the isolated session, including late startup.
No service or browser is started by offline planning or the local tests.

Observe returns `{status:'passed',metrics,checks,proofs}` only after actual
observations. Metrics are measured width (innerWidth), height (innerHeight),
dpr, mobile, touch, language, direction and theme. Each named check exported by
the entry point is required in every cell. Keyboard navigation must visibly
focus controls; dialog focus must be contained and Escape must restore its
invoker. Reduced motion must be measured, long Arabic content must be populated,
and overflow, safe-area clearance, 44-pixel touch floors and 16-pixel phone input
floors must be checked. Language changes must preserve element identity, input
values, password, private file selection, query and operation reference without
writes, submission or upload. Inspect storage, cookies and offline caches for
private retention; do not include passwords or private bytes in returned data.
Sidebar placement must match the language direction.

N01 and N05 proof records require schema_version 1, boundary connected, state
passed, signed_in true and nonempty operation_id, actor_id and provider_revision.
The owning proof must exercise current signed-in service operations using its
published versioned interface, including negative and recovery cases. Assertions
or cached badges alone are insufficient. Fixture results are separate and cannot
satisfy these records. The dispatcher retains selected metrics, check names, bounded proof references
and fixed failure codes; adapters must never put private data in errors. Screenshots must exclude
private evidence and contain the exact full viewport at device pixel ratio.
Before each capture the dispatcher removes the cell's previous screenshot.
Only a missing-file removal error is accepted. Capture must write a fresh file;
a no-op capture cannot reuse an earlier image, and removal failure fails the cell.
Injected file interfaces therefore also provide `unlink(path)` with filesystem
error codes, alongside `readFile`, `writeFile` and `mkdir`.

A matrix physical_device_record names an externally supplied JSON record with
schema_version 1, boundary physical-device, state passed, device, observed_at,
observer and all four phone cell keys in cells. This records externally reviewed
physical evidence; emulation cannot produce it. Missing or incomplete evidence
keeps the required result nonzero. Record provenance must be reviewed separately.

Current boundaries: connected browser, database, restore, load and physical-device
proof remain deferred. N01/N05 adapter integration remains deferred until the
current owning interface is assembled. Earlier fixture captures establish none
of these results. Local tests replace all process, network, browser and file
side effects except reading the owned matrix. No release acceptance is implied.

The matrix `feature_manifest` is null until the owning feature inventory is
available. Null or invalid mappings add the required failure `feature-manifest`.
Version 1 is `{schema_version:1,revision,features}` with exactly 64 distinct
`feature_id` entries, each mapping to `proof_id` and `proof_revision`. These
bounded string references identify the published owning proofs; inventory and
mapping provenance require independent review. Do not invent production mappings.
Offline planning exposes this contract and the required feature count.

Observation requests include the validated `featureManifest`. Each cell must
return `feature_proofs` keyed by every mapped feature identifier. Each record
binds schema_version 1, manifest_revision, feature_id, proof_id, proof_revision
and the exact cell key in `cell`, with boundary connected, state passed,
signed_in true and bounded string operation_id, actor_id and provider_revision.
It also requires `scenarios:{journey:'passed',negative:'passed',recovery:'passed'}`.
Every reference must match the requested mapping; fixture or stale records cannot
satisfy coverage. Only these selected fields enter the report. Missing coverage
fails the cell and keeps the command nonzero regardless of device evidence.
The same operation reference must come from the actual owning operation; language
changes cannot create a replacement reference. Prerequisite records and external
device records do not stand in for any feature journey. The default manifest
leaves feature coverage deferred, independently of the connected adapter.
