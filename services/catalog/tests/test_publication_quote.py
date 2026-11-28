"""Publication previews follow the current pricing request and snapshot contract."""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from bt_contracts.pricing.quotes.models import QuoteRequest, QuoteSnapshot
from bt_contracts_core.errors import PublicError
from modules.listings.fixtures import publication_quote_request, quote_operation
from modules.listings.quotes import publication_quote

ROOT = Path(__file__).resolve().parents[3]


def test_import_request_matches_current_pricing_contract():
    listings = json.loads((ROOT / "demo/listings.json").read_text())["listings"]
    for item in listings:
        row = {"id": "00000000-0000-4000-8000-000000005000", "revision": 3,
               "facts": {"price_minor": item["price_minor"], "currency": "USD"}}
        request = QuoteRequest.model_validate(publication_quote_request(row))
        assert request.purpose == "purchase"
        assert request.source == "sample"
        assert request.schedule_id == "usd-v2"
        assert request.price_minor == item["price_minor"]
        assert request.subject_id == UUID(row["id"])
        assert request.subject_revision == row["revision"]


def snapshot():
    value = json.loads((ROOT / "packages/contracts-pricing/quotes/fixtures/sample-quote.v1.json").read_text())
    value["schedule_id"] = "usd-v2"
    value["policy"]["revision"] = 2
    return QuoteSnapshot.model_validate(value).model_dump(mode="json")


def accept(value):
    return publication_quote(
        value,
        body=SimpleNamespace(fee_quote_id=UUID(value["id"]), rules_version="usd-v2"),
        row={"id": UUID(value["subject_id"]), "revision": value["subject_revision"],
             "facts": {"price_minor": value["price_minor"], "currency": "USD"}},
        owner_id=UUID(value["owner_id"]),
        accepted_at=datetime.fromisoformat(value["created_at"]),
    )


def test_current_snapshot_authorizes_publication_preview():
    value = snapshot()
    assert accept(value) == value


@pytest.mark.parametrize("field, replacement", [
    ("purpose", "offer"), ("schedule_id", "sample-v1"),
    ("source", "listing"), ("source_verified", True),
    ("policy", {}), ("payable_minor", 1),
])
def test_incompatible_publication_snapshot_is_rejected(field, replacement):
    value = snapshot()
    value[field] = replacement
    with pytest.raises(PublicError):
        accept(value)


def test_quote_retry_key_tracks_revision_and_expiry_window():
    assert quote_operation("test-listing", 3, now=601) == quote_operation("test-listing", 3, now=1199)
    assert quote_operation("test-listing", 3, now=601) != quote_operation("test-listing", 4, now=601)
    assert quote_operation("test-listing", 3, now=601) != quote_operation("test-listing", 3, now=1200)
