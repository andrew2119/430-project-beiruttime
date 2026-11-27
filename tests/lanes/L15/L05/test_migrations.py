import json
from pathlib import Path


def test_publication_abort_migration_is_registered_in_its_owning_module():
    root = Path(__file__).resolve().parents[4]
    module_root = root / "services/catalog/modules/listings/revisions"
    registration = json.loads((module_root / "module.json").read_text())
    migrations = registration["migrations"]
    migration = "migrations/L15_0003_publication_abort.sql"

    assert registration["id"] == "L15.listing-revisions"
    assert migration in migrations
    assert migrations == sorted(set(migrations))
    for relative in migrations:
        path = (module_root / relative).resolve()
        assert path.is_relative_to(module_root.resolve())
        assert path.is_file()
        assert path.name.startswith("L15_")
    assert "ADD COLUMN review_denied boolean NOT NULL DEFAULT false" in (
        module_root / migration
    ).read_text()
    earlier = json.loads((module_root.parent / "module.json").read_text())
    assert migration not in earlier["migrations"]
