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
   - `web tests (1/3)` to `(3/3)`: every web Vitest suite, split with Vitest's own `--shard`.
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

Every matrix sets `fail-fast: false`, and no job waits for another except on the build it needs:

| Job | What it runs |
| --- | --- |
| `service (<name>)` x 9 | that service's full pytest profile against its own PostgreSQL |
| `integration lanes` | the sprint-1 integration lane tests |
| `web lint and types` | lint, type check and the money format test |
| `web tests (n/3)` x 3 | one Vitest shard of every web suite |
| `web build` | the production web build, kept as the `web-build` artifact for three days |
| `images and container smoke` | every Compose image, built with layers cached in the Actions cache, then `scripts/smoke.sh` |
| `stage (native)` | the nine services and the web from the build, readiness of each |
| `stage (smokes)` | the HTTP smokes, the connected walkthrough, the origin proof and the proxy proof |
| `stage (browser)` | the browser matrix and the locale and theme screenshots in headless Chrome |
| `stage (scenarios)` | the E06 contract tests and preparation manifest, the E04 synthetic restore and the E09 rehearsal contract tests |
| `native stack lifecycle` | `scripts/native-stack.py` start, smoke, supervised shutdown and stop, on its own PostgreSQL 17 |
| `every required test ran` | `verify.py full` |

Each stage job starts its own stack from the build artifact on its own PostgreSQL.
Nothing else passes between jobs, so rerunning only the failed jobs is always valid.
Pushes to `main` queue one after another; a new push to a group pull request cancels its run in progress.

## The pass rule

A job passes only when its own runner exits 0, every required test in it runs, and nothing required is skipped or pending.
Each job writes a one-line report and publishes it as the `report-<suite>` artifact, kept for three days.
The last job of each workflow reads those reports and `required.json` and fails if:

- a required job did not succeed, or a job the plan did not reach ran and failed;
- a report is missing or not ok;
- a service or the lanes collected a different set of tests than passed, or fewer than their files declare;
- the web shards did not list every web suite of the tree exactly once, or the tests they ran differ from the listed tests in count or identity;
- a stage did not report exactly its pinned steps.

## Running a helper

Each helper's usage is at the top of its file.

| Helper | Needs |
| --- | --- |
| `services.py <service> <report>` | `db-init.sh` on PostgreSQL 17 at 127.0.0.1:54329 and the `python-env` action |
| `lanes.py <report>` | the `python-env` action |
| `web-checks.sh <report>` and `vitest.py <shard> <total> <report>` | the `node-env` action |
| `stage.py <stage> <report>` | both environments, the database and a production build in `web/.next` |
| `n01.py <report>` | both environments, the build, PostgreSQL 17 in `/usr/lib/postgresql/17/bin`, port 54329 free and `sudo` |
| `images.py build` then `images.py smoke <report>` | Docker with Buildx |
| `verify.py <full or light> <needs.json> <reports>` | the reports and the workflow's `needs` |
