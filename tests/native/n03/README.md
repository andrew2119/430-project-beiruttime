# Catalog and Discovery proof roots

`BT_MODULES_PATH` supplies the Catalog module directory. A supplied Discovery
module directory is normalized to its Catalog parent for Catalog reads; Discovery
migration inventory always receives only the `discovery` child. Module manifests
must identify `L03.listings`, `L03.media` and `L04.discovery`.

`BT_NATIVE_CONTRACT_ROOT` supplies a distribution root with
`bt_contracts/catalog/discovery/fixtures` beneath it. The required fixture names
come from the repository's `catalog.discovery.v1` registration when available.
An invalid explicit root fails rather than selecting another directory.

Without explicit roots, module resolution checks the service-relative Catalog
module tree, then `/app/modules`. Contract resolution checks the registered
repository directory, then `/opt/domain-contracts/bt_contracts/catalog/discovery/fixtures`.
The container layout also works without a repository registration file.

The pure path interface in `tests/lanes/L04/browser_fixture.py` exports `catalog_modules(source)`,
`discovery_modules(source)` and `contract_fixtures(source)`, each returning a
`Path`. `source` is the calling proof's file location. The existing lane-only container layout contains the resolver; no additional
container copy is required. `paths.py` exposes the same functions to bounded checks.

Run the bounded checks with:

```sh
python3 -m unittest discover -s tests/native/n03 -p 'test_*.py' -v
```

These layout checks do not establish provider, database or browser acceptance.
