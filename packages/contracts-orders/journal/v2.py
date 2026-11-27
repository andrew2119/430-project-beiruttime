"""Retained USD money and collection bindings, not execution or refund permission."""

from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictInt, model_validator
from .facts import PaidOrderFact
from bt_contracts_core.models import Contract

Minor = StrictInt
OrderKind = Literal["sale", "service_job", "customization_job"]


def percentage(amount: int, basis_points: int) -> int:
    return (amount * basis_points + 5000) // 10000


class AcceptedMoney(Contract):
    order_kind: OrderKind
    currency: Literal["USD"]
    price_minor: Minor = Field(gt=0, le=9_000_000_000_000)
    buyer_fee_minor: Minor = Field(ge=0)
    seller_commission_minor: Minor = Field(ge=0)
    seller_net_minor: Minor = Field(ge=0)
    shipping_minor: Minor = Field(ge=0)
    tax_minor: Minor = Field(ge=0)
    payable_minor: Minor = Field(gt=0, le=18_000_000_000_000)
    # A separately accepted conditional return line, never included twice.
    return_fee_minor: Minor | None = Field(ge=0, default=None)
    refundable_max_minor: Minor = Field(gt=0)

    @model_validator(mode="after")
    def exact_components(self):
        if self.seller_commission_minor != percentage(self.price_minor, 500):
            raise ValueError("The payee owes the retained five percent fee")
        if self.seller_net_minor != self.price_minor - self.seller_commission_minor:
            raise ValueError("The payee fee is deducted only once")
        if self.refundable_max_minor != self.price_minor:
            raise ValueError("Customer principal is separate from fees")
        if self.order_kind == "sale":
            if self.buyer_fee_minor != percentage(self.price_minor, 300):
                raise ValueError("Watch buyer fee is three percent")
        elif self.buyer_fee_minor or self.shipping_minor or self.tax_minor:
            raise ValueError("Jobs have no extra customer surcharge or conditional transport in their total")
        if self.payable_minor != self.price_minor + self.buyer_fee_minor + self.shipping_minor + self.tax_minor:
            raise ValueError("Retained customer components must balance")
        return self


class PaidOrderFactV2(PaidOrderFact):
    state: Literal["awaiting_notification", "awaiting_payment", "payment_unknown", "expired_fenced", "expired_released", "paid_held"]
    deadline: AwareDatetime | None
    notified_at: AwareDatetime | None
    initiation_extended_until: AwareDatetime | None
    payment_method: Literal["card", "whish", "omt"] | None
    notification_state: Literal["pending", "notified"]
    order_kind: OrderKind
    retained_economics: AcceptedMoney | None


class SavedSimulatedMethod(Contract):
    id: UUID
    payer_id: UUID
    organization_id: UUID | None
    route: Literal["card", "whish", "omt"]
    reference: str = Field(pattern=r"^SIM-METHOD-[0-9a-f-]{36}$")
    simulated: Literal[True] = True

    @model_validator(mode="after")
    def synthetic_reference(self):
        if self.reference != "SIM-METHOD-" + str(self.id):
            raise ValueError("Use the exact saved synthetic method reference")
        return self


class SellerChargeBinding(Contract):
    operation_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    order_id: UUID
    quote_id: UUID
    quote_revision: Minor = Field(ge=1)
    purpose: Literal["failed_authentication", "job_fee"]
    # Current failed inspection, or the retained authorized job refund decision.
    source_id: UUID
    source_revision: Minor = Field(ge=1)
    method: SavedSimulatedMethod
    amount_minor: Minor = Field(gt=0, le=18_000_000_000_000)
    currency: Literal["USD"] = "USD"
    simulated: Literal[True] = True


class JobRefundFunding(Contract):
    """A principal allocation, never a confirmed refund or collected fee."""

    permitted_customer_refund_minor: Minor = Field(ge=0)
    business_fee_receivable_minor: Minor = Field(ge=0)
    # Unknown collection never counts as paid and cannot reduce a customer's refund.
    confirmed_fee_collection_id: UUID | None = None
    customer_fee_deduction_minor: Literal[0] = 0
    refund_authority: Literal[False] = False


def failed_charge_minor(money: AcceptedMoney) -> int:
    if money.order_kind != "sale" or money.return_fee_minor is None:
        raise ValueError("A watch sale with an explicitly accepted return line is required")
    return money.seller_commission_minor + money.return_fee_minor


def job_refund_funding(money: AcceptedMoney, permitted_principal_minor: int) -> JobRefundFunding:
    if money.order_kind == "sale" or type(permitted_principal_minor) is not int or not 0 <= permitted_principal_minor <= money.price_minor:
        raise ValueError("A permitted job principal allocation is required")
    return JobRefundFunding(permitted_customer_refund_minor=permitted_principal_minor,
                            business_fee_receivable_minor=money.seller_commission_minor)
