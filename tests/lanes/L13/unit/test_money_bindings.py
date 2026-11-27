from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from bt_contracts_core.errors import PublicError


def amounts(kind="sale", **changes):
    return {"order_kind": kind, "currency": "USD", "price_minor": 500000,
            "buyer_fee_minor": 15000 if kind == "sale" else 0, "seller_commission_minor": 25000,
            "seller_net_minor": 475000, "shipping_minor": 0, "tax_minor": 0,
            "payable_minor": 515000 if kind == "sale" else 500000,
            "return_fee_minor": 2000, "refundable_max_minor": 500000, **changes}


def money_contract(lane_modules):
    return lane_modules("bt_contracts.orders.journal.v2", "packages/contracts-orders/journal/v2.py")


def test_sale_retains_5150_total_250_fee_and_5000_refund_maximum(lane_modules):
    contract = money_contract(lane_modules)
    money = contract.AcceptedMoney(**amounts())
    assert money.payable_minor == 515000
    assert money.seller_commission_minor == 25000
    assert money.refundable_max_minor == 500000
    assert contract.failed_charge_minor(money) == 27000
    with pytest.raises(ValueError):
        contract.failed_charge_minor(money.model_copy(update={"return_fee_minor": None}))


@pytest.mark.parametrize("kind", ["service_job", "customization_job"])
def test_full_job_refund_keeps_business_fee_outside_customer_principal(lane_modules, kind):
    contract = money_contract(lane_modules)
    money = contract.AcceptedMoney(**amounts(kind))
    funding = contract.job_refund_funding(money, 500000)
    assert money.payable_minor == 500000 and money.seller_net_minor == 475000
    assert funding.permitted_customer_refund_minor == 500000
    assert funding.business_fee_receivable_minor == 25000
    assert funding.customer_fee_deduction_minor == 0
    assert funding.confirmed_fee_collection_id is None
    assert funding.refund_authority is False
    with pytest.raises(ValueError):
        contract.job_refund_funding(money, 500001)
    with pytest.raises(ValueError):
        contract.failed_charge_minor(money)


@pytest.mark.parametrize("change", [{"buyer_fee_minor": 15000, "payable_minor": 515000},
    {"seller_net_minor": 450000}, {"refundable_max_minor": 475000},
    {"currency": "LBP"}, {"price_minor": True}, {"return_fee_minor": False},
    {"shipping_minor": 2000, "payable_minor": 502000}])
def test_job_does_not_double_fee_or_surcharge_customer(lane_modules, change):
    contract = money_contract(lane_modules)
    with pytest.raises(ValidationError):
        contract.AcceptedMoney(**amounts("service_job", **change))


def test_saved_method_binding_is_synthetic_and_exact_not_a_real_credential(lane_modules):
    contract = money_contract(lane_modules)
    method_id = uuid4()
    data = {"id": method_id, "payer_id": uuid4(), "organization_id": None,
            "route": "card", "reference": "SIM-METHOD-" + str(method_id)}
    assert contract.SavedSimulatedMethod(**data).simulated
    for changes in ({"reference": "SIM-METHOD-" + str(uuid4())}, {"route": "wire"},
                    {"card_number": "not-accepted"}, {"simulated": False}):
        with pytest.raises(ValidationError):
            contract.SavedSimulatedMethod(**(data | changes))


def test_one_cent_half_up_is_explicit(lane_modules):
    contract = money_contract(lane_modules)
    assert contract.percentage(10, 500) == 1
    assert contract.percentage(9, 500) == 0


@pytest.mark.asyncio
async def test_retention_requires_all_exact_fee_components_before_any_write(lane_modules):
    money_contract(lane_modules)
    quote = lane_modules("service_app.exact_quote", "services/orders/runtime/service_app/exact_quote.py")
    order = {"id": uuid4(), "quote_id": uuid4(), "buyer_id": uuid4(), "organization_id": None,
             "currency": "USD", "total_minor": 515000, "order_kind": "sale"}
    snapshot = amounts() | {"id": str(order["quote_id"]), "owner_id": str(order["buyer_id"]), "revision": 2}
    tx = SimpleNamespace(execute=AsyncMock())
    await quote.retain(tx, order, snapshot, 1, "private")
    tx.execute.assert_awaited_once()
    tx.execute.reset_mock()
    for field in ("seller_commission_minor", "seller_net_minor"):
        incomplete = {key: value for key, value in snapshot.items() if key != field}
        with pytest.raises(PublicError, match="retained_money_invalid"):
            await quote.retain(tx, order, incomplete, 1, "private")
    tx.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_paid_fact_versions_preserve_old_shape_without_inventing_clock(lane_modules):
    contract = money_contract(lane_modules)
    kernel = lane_modules("service_app.orders_kernel", "services/orders/runtime/service_app/orders_kernel.py")
    raw = amounts()
    raw.pop("order_kind")
    raw.pop("refundable_max_minor")
    row = {key: uuid4() for key in ("id", "watch_id", "listing_id", "buyer_id", "seller_id", "quote_id", "journal_group_id")}
    row.update(organization_id=None, state="paid_held", currency="USD", total_minor=515000, revision=3,
               deadline=datetime.now(timezone.utc), is_demo=True, quote_revision=2, listing_revision=1,
               seller_type="private", snapshot=raw, order_kind="sale", notified_at=datetime.now(timezone.utc),
               initiation_extended_until=None, payment_method="card")
    tx = SimpleNamespace(fetchrow=AsyncMock(return_value=row))
    v1 = await kernel.paid_fact(tx, row["id"])
    assert contract.PaidOrderFact.model_validate(v1).paid
    assert "notified_at" not in v1 and "order_kind" not in v1
    v2 = contract.PaidOrderFactV2.model_validate(await kernel.paid_fact(tx, row["id"], version=2))
    assert v2.paid and v2.retained_economics.refundable_max_minor == 500000
    row.update(state="awaiting_notification", notified_at=None, deadline=None, journal_group_id=None)
    with pytest.raises(PublicError, match="contract_upgrade_required"):
        await kernel.paid_fact(tx, row["id"])
    pending = contract.PaidOrderFactV2.model_validate(await kernel.paid_fact(tx, row["id"], version=2))
    assert pending.notified_at is pending.deadline is None and not pending.paid
