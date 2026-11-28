# Beirut Time CI

Two GitHub Actions workflows run on standard Ubuntu runners.
They need no secrets, read the repository only, and pin every action by its full commit.

## Light checks (every pull request)

`.github/workflows/light-checks.yml` runs on every pull request to `main`.
It is a fast signal for the piece being changed, not the full suite, and is never reported as one.

1. `plan` maps the changed paths to the light suites they reach (`changed.py`).
2. The reached suites run as independent jobs, so one red job never stops the others:
   - `service (<name>)`: one job per reached service, each with its own PostgreSQL;
   - `integration lanes`: the sprint-1 integration lane tests;
   - `web lint and types`: lint, type check and the money format test;
   - `web tests (1/4)` to `(4/4)`: every web Vitest suite, split across four shards (see below).
3. `every reached test ran` (`verify.py light`) checks each reached job's report.

A new push to the same pull request cancels the run still in progress.

### The changed-path map

`changed.py` compares the pull request's merge commit with the tip of `main`.
Each changed path takes the first rule that matches it:

| Paths | Reach |
| --- | --- |
| `.github/`, `packages/`, `contracts/`, `infra/foundation/`, `scripts/native-services.json`, `package.json`, `pnpm-lock.yaml`, `pnpm-workspace.yaml`, `tsconfig.base.json`, `.gitignore`, `.dockerignore` | every light suite |
| `services/_template/`, `tests/foundation/`, `tests/lanes/L00/` | every service |
| `services/<name>/` | that service |
| `web/`, `tests/lanes/L04/`, `L07/`, `L08/`, `L09/`, `L11/` | the web jobs |
| `tests/integration/sprint-1/` | the integration lanes |
| `docs/`, `README.md`, `infra/compose/`, `compose.yaml`, `Makefile`, `.railway/` | no light suite; the full suite covers them |
| anything else | every light suite |

If the change cannot be read, every light suite runs.
An unknown path can only widen the check, never shrink it.
The plan job writes the reason for each path to its job summary.
To see what a change reaches locally: `python3 .github/ci/changed.py <path> ...`.

## Tests (the full suite)

`.github/workflows/tests.yml` runs on every push to `main`, on demand from the Actions tab, and on group pull requests.
A group pull request is one whose head branch starts with `bt/group-`, for example `bt/group-auctions-1`.
Use that prefix for a branch that gathers several pieces and needs the full suite before it merges.
Other pull requests show the Tests run as skipped.

Every matrix sets `fail-fast: false`.
`tested commit` comes first and names the commit under test; the other jobs start together after it, and only the stage parts and the native stack lifecycle also wait for the build:

| Job | What it runs |
| --- | --- |
| `service (<name>)` x 9 | that service's full pytest profile against its own PostgreSQL |
| `integration lanes` | the sprint-1 integration lane tests |
| `web lint and types` | lint, type check and the money format test |
| `tested commit` | the commit under test, written to its job summary |
| `web tests (n/4)` x 4 | this shard's share of the web Vitest suites |
| `web build` | the production web build, kept as the `web-build` artifact for three days |
| `images and container smoke` | every Compose image, built from the layers in the Actions cache, then `scripts/smoke.sh`; it reads the cache and never writes it |
| `image cache (n/4)` x 4 | this shard's share of the images, built only to write their layers to the Actions cache for later runs; shard 1 is the web image alone |
| `stage (native)` | the nine services and the web from the build, readiness of each |
| `stage (smokes)` | the HTTP smokes and the connected walkthrough, with a scripted possession review that is not physical inspection (see below) |
| `stage (origin-proof)` | the origin proof, with its own production web build |
| `stage (proxy-proof)` | the proxy proof, with its own production web build |
| `stage (browser-desktop)` | the desktop browser matrix and its four locale and theme screenshots in headless Chrome |
| `stage (browser-phone)` | the phone browser matrix and its four locale and theme screenshots |
| `stage (scenarios-e06)` | the E06 contract tests and preparation manifest |
| `stage (scenarios-e04)` | the E04 synthetic restore |
| `stage (scenarios-e09)` | the E09 rehearsal contract tests |
| `native stack lifecycle` | `scripts/native-stack.py` start, smoke, supervised shutdown and stop, on its own PostgreSQL 17 |
| `every required test ran` | `verify.py full` |

Each stage part starts its own stack from the build artifact on its own PostgreSQL, runs its own share of the stage's steps and stops the stack.
`required.json` lists the parts of each stage and the steps of each part; no step runs in two parts.
Nothing else passes between jobs, so rerunning only the failed jobs is always valid.
Two jobs stay whole on purpose: the container smoke needs every image in the same Docker engine, and the native stack lifecycle is one start-to-stop run of the same stack.
The container smoke stays short anyway: uploading the image layers is the slow part, and the four image cache jobs do it beside the smoke instead of before it.
A Tests run has 33 jobs and a Light checks run at most 17, each within the account's 40 jobs at a time.
Pushes to `main` queue one after another; a new push to a group pull request cancels its run in progress.

### The web shards

`vitest.py` plans the shards the same way on every runner, from the tree alone.
A suite with up to 12 test files runs whole in one shard.
A larger suite is cut into parts with Vitest's own `--shard`, one part per shard, at most four.
The parts and whole suites are then packed onto the four shards so each gets about the same number of test files.
Each suite is also listed once, with `vitest list`, in the shard that runs its first part.
To see the plan locally: `python3 -c "import sys; sys.path.insert(0, '.github/ci'); import vitest; print(vitest.plan(4))"`.
Before its suites, each shard makes the navigation index with `node scripts/generate-nav.mjs` in `web/`: the index is generated, kept out of git, and read by some suites.

### The scripted possession review (not physical inspection)

`stage (smokes)` runs the connected walkthrough through `walkthrough.py`, every phase, unchanged but for one thing.
When publication stops because the private demo drafts wait for a possession review, the driver takes each draft through the walkthrough's own review steps (challenge, submit, assign, inspect, decide) and publishes again.
The inputs are scripted test inputs: the frozen test icon `web/public/icons/bt-192.png` as the photo, a fixed approved verdict, and the operator as reviewer with no credentials file.
This is not physical inspection.
Nobody looks at a watch, so a pass shows that the review routes work, not that anyone holds the watch; a real person's review stays unproven.
The step name, the driver and its log lines (`N05-SCRIPTED-REVIEW ...`, ending with a summary) all say so.

The inputs come from `scripted-review/n05-scripted-actor.py`, over the file protocol in `scripted-review/listing_coordinator.py`.
`walkthrough.py` pins the actor's sha256 and refuses a changed copy, so any change to it is reviewed again.
The review is test only: it runs on the job's own disposable stack, in no product or deploy path, and uses no secrets.
It is bounded to four publication attempts, fifteen review calls and 300 seconds.
A tree whose publication passes without a review runs unchanged, with nothing scripted, and any other publication failure fails as before.

### When a stage part fails

- The smokes part prints the walkthrough's publication child records, their six known fields only; any other field is named without its value.
- A browser part gives the browser its own temporary folder; when its step fails, it prints the names left in that folder and the Chrome processes still running.
- When a browser check fails and closing its browser session fails too, `browser.mjs` reports both errors.

## Testing one pull request on demand

Both workflows take an optional pull request number when started from the Actions tab (or `gh workflow run <workflow> -f pr=<number>`).
The run then tests that pull request's code:

- its merge commit with `main` (`refs/pull/<number>/merge`) when GitHub has one;
- otherwise its head commit (`refs/pull/<number>/head`).

The tests always use the CI files of the workflow's own commit, so a pull request that predates them can still be tested.
Light checks plans from the changed paths when it found the merge commit, and runs every light suite when it tested the head commit.
Each pull request number has its own concurrency group, so runs for different pull requests go side by side and never cancel each other.
A dispatch never shares a group with the pull request's own runs.
Without a number, Light checks runs every light suite and Tests runs the full suite on the chosen branch.

## The pass rule

A job passes only when its own runner exits 0, every required test in it runs, and nothing required is skipped or pending.
Each job writes a one-line report and publishes it as the `report-<suite>` artifact, kept for three days.
The last job of each workflow reads those reports and `required.json` and fails if:

- a required job did not succeed, or a job the plan did not reach ran and failed;
- a report is missing or not ok;
- a service or the lanes collected a different set of tests than passed, or fewer than their files declare;
- the web shards did not list every web suite of the tree exactly once, did not run every part of every suite exactly once, or the tests they ran differ from the listed tests in count or identity;
- a web test was skipped, pending, todo or failed, unless it is a known gap pinned in `required.json`;
- a pinned gap was not reported skipped exactly once: it passed, went missing, was renamed or was reported twice;
- a stage part did not report exactly its pinned steps, a step ran in two parts, or the two browser parts did not run every pinned browser check exactly once;
- `required.json` names different services from `scripts/native-services.json`.

The image cache jobs are outside the pass rule: they test nothing, the check job does not wait for them, and a failed one shows red on its own.

### Known gaps

Two web tests always skip on a runner, and `required.json` pins each by suite, file and full title:

| Test | Why it skips |
| --- | --- |
| `web/features/counteroffers/subject-switch.test.tsx` > clears the mounted form on subject switch and ignores the old completion | it needs the optional test package `react-test-renderer`, which is not installed |
| `web/features/proxy-bid/pricing-connected.test.ts` > connected non-binding fee preview > persists the exact sample preview/review privately and grants no reservation authority | the opt-in connected pricing test, which runs only with `BT_L06_CONNECTED_PRICING=1` |

A pinned gap is never counted as run or passed.
The check job lists each as `NOT PASSED` in its output and job summary.
Remove the entry from `required.json` when its test is fixed to run, or the run turns red.

### Comparing two runs of the same tree

The check job prints, per suite, the counts and the sha256 of its sorted test identities (`ids`), then the tested commit, its tree, and its tree without `.github`.
Two commits that differ only in `.github` share the tree without `.github`, so their runs can be compared suite by suite.

## Running a helper

Each helper's usage is at the top of its file.

| Helper | Needs |
| --- | --- |
| `services.py <service> <report>` | `db-init.sh` on PostgreSQL 17 at 127.0.0.1:54329 and the `python-env` action |
| `lanes.py <report>` | the `python-env` action |
| `web-checks.sh <report>` and `vitest.py <shard> <total> <report>` | the `node-env` action |
| `stage.py <part> <report>` | both environments, the database and a production build in `web/.next` |
| `n01.py <report>` | both environments, the build, PostgreSQL 17 in `/usr/lib/postgresql/17/bin`, port 54329 free and `sudo` |
| `images.py build` then `images.py smoke <report>`, and `images.py cache <shard> <count>` | Docker with Buildx; `build` and `cache` also need the Actions cache settings, so the workflow starts them from `actions/github-script` |
| `walkthrough.py <run-dir> <origin>` | the stack `stage.py smokes` starts, with its run folder |
| `verify.py <full or light> <needs.json> <reports>` | the reports and the workflow's `needs` |
