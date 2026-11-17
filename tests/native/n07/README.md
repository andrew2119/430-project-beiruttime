# Native transport proof contract

Both entry points publish JSON schema version 1 with `--plan`. Planning performs
no copy, build, socket, process or browser operation. Consumers read `kind`,
`cases`, `assertions`, `browser`, `connected_requires` and `container_publication`.
Origin cases bind the trusted-edge setting, request headers and exact status.
Nested cases bind route, locale, method, probe, query and exact status; redirects
retain their status set, query and one-hop limit. Header-free, query-free
GET/HEAD probes run alongside the cookie and query variants for each authority.
Case headers are explicit in the plan.

Execution requires a fresh `--run-dir` outside the source tree. Each proof owns
its named child directory, preserves it on failure and refuses reuse. The
pre-overlay source fingerprints include the current registration and fixture
bytes. Installed dependency trees are copied, with links into the input tree rebased
to the run copy, including workspace packages and the dependency store. External
links retain their installed targets; other source symlinks are refused. Only the copied registrations and copied
fixture routes change. For the nested proof, each other lane registration is
wrapped in the run copy to filter the two fixture paths while preserving all
other entries; its original bytes remain in a sibling module. The fixture is
the sole owner of those paths during the proof. Existing pages for the exact proof routes, including
route-group variants, are removed only from the fingerprinted run copy before
the fixture pages are installed. Unrelated pages and layouts are retained. Builds and probes fail nonzero on errors. Builds have a 900-second deadline
and an isolated process group, terminated and reaped on success, failure, timeout
or interruption; remaining descendants receive a final kill signal.

`--origin` selects an explicit-port loopback HTTP authority. `--loopback` on the
nested proof places a transparent local transport in front of the private
production listener. The direct probe exercises numeric loopback authority
normalization separately from the public authority. The origin upstream echoes
transport metadata only and implements no business service.

Browser execution fails nonzero until the N09 interface is available. The plan
retains its bilingual, theme and geometry assertions as deferred coverage.
N01 and N08 connected execution remains deferred. Native results never establish
container publication, database, restore, load or physical-device coverage.
