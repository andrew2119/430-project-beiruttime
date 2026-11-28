"""Versioned offering forms; values and operation references are locale independent."""
from decimal import Decimal, InvalidOperation
import re
from typing import Literal
from uuid import UUID
from pydantic import Field, StrictInt
from bt_contracts.catalog.options import (
    ColorDetails, MaterialDetails, DialDetails, SophisticationDetails, OptionWrite, Kind,
)

SCHEMA_VERSION = "catalog.offering-form.v1"
DETAILS = {
    "color": ColorDetails,
    "material": MaterialDetails,
    "dial": DialDetails,
    "sophistication": SophisticationDetails,
}
LABELS = {
    "color": {"en": "Color and finish", "ar": "اللون والتشطيب"},
    "material": {"en": "Material and grade", "ar": "المادة والدرجة"},
    "dial": {"en": "Dial, hands and markers", "ar": "الميناء والعقارب والمؤشرات"},
    "sophistication": {"en": "Finishing package", "ar": "حزمة التشطيب"},
}


class OfferingReceipt(OptionWrite):
    schema_version: Literal["catalog.offering-receipt.v1"]
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,100}$")
    subject_id: UUID
    watch_id: None
    actor_id: UUID
    organization_id: UUID
    state: Literal["saved"]
    revision: StrictInt = Field(ge=1, le=2147483647)
    pending_reason: None
    next_actor: None
    next_review_at: None
    brand_id: UUID
    kind: Kind
    id: UUID


def dollar_cents(value: str) -> int:
    """Accept exact dollar input without rounding or binary floating point."""
    normalized = value.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789."))
    if not re.fullmatch(r"[0-9]{1,10}(?:\.[0-9]{1,2})?", normalized):
        raise ValueError("Enter dollars with at most two decimal places. أدخل الدولار بمنزلتين عشريتين كحد أقصى.")
    try:
        cents = int(Decimal(normalized) * 100)
    except InvalidOperation:
        raise ValueError("Invalid dollar amount. مبلغ الدولار غير صالح.") from None
    if cents > 999999999999:
        raise ValueError("The dollar amount is too large. مبلغ الدولار كبير جداً.")
    return cents


def active_definition(kind, definition):
    return kind != "sophistication" or definition.get("details", {}).get("currency") == "USD"


def form(kind):
    details = DETAILS[kind].model_json_schema()
    if kind == "sophistication":
        details["properties"]["currency"] = {"const": "USD", "type": "string"}
    return {
        "schema_version": SCHEMA_VERSION,
        "dimension": kind,
        "label": LABELS[kind],
        "write_schema": OptionWrite.model_json_schema(),
        "details_schema": details,
        "currency": "USD",
        "money_input": "dollars",
        "money_storage": "integer_cents",
        "operation_header": "Idempotency-Key",
        "write_method": "PUT",
        "write_path": "/v1/brand-options/brands/{brand_id}/{kind}/{option_id}",
        "lookup_path": "/v1/brand-options/brands/{brand_id}/operations/{operation_id}",
        "states": {
            "draft": {"en": "Review the offering before saving.", "ar": "راجع العرض قبل الحفظ."},
            "pending": {"en": "Check the same operation before retrying.", "ar": "تحقق من العملية نفسها قبل إعادة المحاولة."},
            "saved": {"en": "Offering revision saved.", "ar": "تم حفظ إصدار العرض."},
            "stale": {"en": "Reload and review the current revision.", "ar": "أعد التحميل وراجع الإصدار الحالي."},
            "denied": {"en": "Ask your business administrator for access.", "ar": "اطلب صلاحية الوصول من مسؤول المنشأة."},
            "unavailable": {"en": "Retry the same operation when available.", "ar": "أعد محاولة العملية نفسها عند توفر الخدمة."},
        },
    }


def display_definition(kind, definition):
    if active_definition(kind, definition):
        return definition
    return {
        'component': definition['component'],
        'label': {
            'en': 'Legacy finishing package unavailable. Choose a current USD offering.',
            'ar': 'حزمة التشطيب السابقة غير متاحة. اختر عرضاً حالياً بالدولار الأمريكي.',
        },
        'base_models': definition['base_models'],
        'calibers': definition['calibers'],
        'available': False,
        'details': {},
    }



def display_receipt(result):
    """Restrict historical money on recovery without changing stored outcomes."""
    visible = dict(result)
    if visible.get("kind") == "sophistication" and not active_definition("sophistication", visible):
        visible.update(display_definition("sophistication", visible))
        visible["restricted_legacy"] = True
    if "selections" in visible:
        visible["selections"] = []
        for selection in result["selections"]:
            item = dict(selection)
            if not active_definition(item["kind"], item["definition"]):
                item["definition"] = display_definition(item["kind"], item["definition"])
                item["restricted_legacy"] = True
                item["current"] = False
            visible["selections"].append(item)
    return visible
