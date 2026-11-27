from pathlib import Path

from bt_runtime.modules import Module


def test_revision_routes_load_as_an_independent_module():
    root = Path(__file__).resolve().parents[4]
    module = Module(
        id="L15.listing-revisions",
        root=root / "services/catalog/modules/listings/revisions",
        routes=("routes.py:router",),
        migrations=(),
        authorization=None,
        fixtures={},
        hooks={},
        workers=(),
    )

    router = module.load("routes.py:router")

    assert any(route.path == "/v1/seller/listings/{listing_id}/revisions" for route in router.routes)
