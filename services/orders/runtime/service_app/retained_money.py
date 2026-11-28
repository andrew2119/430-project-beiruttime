"""Normalize exact retained components without claiming collected fees or release."""

from bt_contracts.orders.journal.v2 import AcceptedMoney
from bt_contracts_core.errors import PublicError
from pydantic import ValidationError


def retained_money(snapshot, order_kind="sale"):
    try:
        return AcceptedMoney.model_validate({
            "order_kind": order_kind,
            **{name: snapshot[name] for name in (
                "currency", "price_minor", "buyer_fee_minor", "seller_commission_minor",
                "seller_net_minor", "shipping_minor", "tax_minor", "payable_minor",
            )},
            "return_fee_minor": snapshot.get("return_fee_minor"),
            "refundable_max_minor": snapshot["price_minor"],
        }).model_dump(mode="json")
    except (ValidationError, KeyError, TypeError):
        raise PublicError("retained_money_invalid", "The retained exact money requires reconciliation.", status=409) from None
