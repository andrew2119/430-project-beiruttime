from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from bt_contracts_core.errors import PublicError


def economics(kind="winner"):
    now = datetime.now(timezone.utc)
    current = {
        "quote_id": str(uuid4()), "quote_revision": 2, "buyer_id": str(uuid4()),
        "source_id": str(uuid4()), "source_revision": 3, "kind": kind,
        "listing_id": str(uuid4()), "listing_revision": 1, "currency": "USD",
        "total_minor": 515000, "expires_at": None, "accepted_at": now.isoformat(),
        "selected_line_ids": [], "terms_digest": None, "schedule_id": "usd-v2",
        "policy_revision": 2, "rounding": "half_up", "status": "valid",
        "economics": "committed", "execution_authority": "not_granted",
    }
    financial = {key: current[key] for key in (
        "quote_id", "quote_revision", "buyer_id", "source_id", "source_revision",
        "currency", "schedule_id", "policy_revision", "rounding", "selected_line_ids", "terms_digest",
    )} | {
        "price_minor": 500000, "buyer_fee_minor": 15000, "seller_commission_minor": 25000,
        "seller_net_minor": 475000, "shipping_minor": 0, "tax_minor": 0, "payable_minor": 515000,
        "minor_unit_exponent": 2, "sample": True, "policy": {},
        "expires_at": None, "reviewed_at": (now - timedelta(days=3)).isoformat(),
        "authority": "retained_read_only",
    }
    if kind == "offer":
        financial.update(source_id=current["listing_id"], source_revision=current["listing_revision"])
    return current, financial


@pytest.mark.parametrize("kind", ["winner", "offer"])
@pytest.mark.parametrize("historical_expiry", [None, "2026-01-01T00:00:00Z"])
def test_committed_economics_outlive_preview_without_granting_execution(lane_modules, kind, historical_expiry):
    module = lane_modules("service_app.exact_quote", "services/orders/runtime/service_app/exact_quote.py")
    current, financial = economics(kind)
    financial["expires_at"] = historical_expiry
    snapshot = module.retained_snapshot(financial, module.current_quote(current))
    assert snapshot["payable_minor"] == 515000
    assert snapshot["seller_commission_minor"] == 25000
    assert snapshot["price_minor"] == 500000
    assert snapshot["authorization_expires_at"] is None


@pytest.mark.parametrize("change", [
    {"economics": "preview"}, {"expires_at": "2027-01-01T00:00:00Z"},
    {"currency": "LBP"}, {"policy_revision": 1}, {"execution_authority": "granted"},
])
def test_preview_legacy_currency_or_unrecognized_authority_cannot_allocate(lane_modules, change):
    module = lane_modules("service_app.exact_quote", "services/orders/runtime/service_app/exact_quote.py")
    current, _ = economics()
    with pytest.raises(PublicError):
        module.current_quote(current | change)


@pytest.mark.parametrize("change", [
    {"buyer_id": str(uuid4())}, {"source_id": str(uuid4())}, {"source_revision": 4},
    {"quote_revision": 3}, {"payable_minor": 515001}, {"schedule_id": "sample-v1"},
    {"selected_line_ids": [str(uuid4())]}, {"terms_digest": "changed"},
])
def test_nonexpiring_is_not_permission_to_change_exact_economics(lane_modules, change):
    module = lane_modules("service_app.exact_quote", "services/orders/runtime/service_app/exact_quote.py")
    current, financial = economics()
    with pytest.raises(PublicError):
        module.retained_snapshot(financial | change, module.current_quote(current))
