import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("notice_contract", ROOT / "packages/contracts-orders/allocation/v3.py")
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


def test_notice_binds_original_intent_buyer_order_and_availability():
    now = datetime.now(timezone.utc)
    intent = {"event_id": uuid4(), "order_id": uuid4(), "buyer_id": uuid4(), "created_at": now - timedelta(minutes=1)}
    order = {"id": intent["order_id"], "buyer_id": intent["buyer_id"]}
    receipt = contract.PaymentNoticeReceipt(**{k: intent[k] for k in ("event_id", "order_id", "buyer_id")},
        notice_id=uuid4(), notified_at=now, verified_delivery_recorded=True)
    assert contract.notice_matches(receipt, intent, order, now)
    for field in ("event_id", "buyer_id", "order_id"):
        assert not contract.notice_matches(receipt.model_copy(update={field: uuid4()}), intent, order, now)
    for invalid_time in (now + timedelta(seconds=1), now - timedelta(minutes=2)):
        assert not contract.notice_matches(receipt.model_copy(update={"notified_at": invalid_time}), intent, order, now)


def test_receipt_requires_verified_delivery_and_aware_original_time():
    body = dict(event_id=uuid4(), order_id=uuid4(), buyer_id=uuid4(), notice_id=uuid4(),
                notified_at=datetime.now(timezone.utc), verified_delivery_recorded=True)
    for changes in ({"verified_delivery_recorded": False}, {"notified_at": datetime.now()}, {"producer": "catalog"}):
        with pytest.raises(ValidationError):
            contract.PaymentNoticeReceipt(**(body | changes))
