"""Small pure boundary checks; database/callback races remain connected proof."""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("payment_clock", ROOT / "services/orders/runtime/service_app/payment_clock.py")
clock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clock)
START = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


def order(**changes):
    return {"currency": "USD", "state": "awaiting_payment", "notified_at": START,
            "deadline": START + timedelta(hours=48), "initiation_extended_until": None, **changes}


def test_no_durable_notice_means_no_deadline():
    assert clock.deadline_for(None) is None
    assert not clock.can_initiate(order(notified_at=None), "card", START)
    assert clock.expiry_decision(order(deadline=None), [], START + timedelta(days=30)) == "wait"


@pytest.mark.parametrize("method,hours", [(None, 48), ("card", 24), ("whish", 48), ("omt", 48)])
def test_method_boundaries(method, hours):
    deadline = START + timedelta(hours=hours)
    assert clock.deadline_for(START, method) == deadline
    if method:
        assert clock.can_initiate(order(), method, deadline - timedelta(microseconds=1))
        assert not clock.can_initiate(order(), method, deadline)
        assert not clock.can_initiate(order(), method, deadline + timedelta(microseconds=1))


def test_one_initiation_window_never_resets_on_retry_or_route_switch():
    extension = clock.initiated_until(order(), "card", START + timedelta(hours=23))
    assert extension == START + timedelta(hours=48)
    extended = order(initiation_extended_until=extension)
    assert clock.initiated_until(extended, "card", START + timedelta(hours=47)) == extension
    assert clock.initiated_until(extended, "omt", START + timedelta(hours=47)) == extension
    assert clock.initiated_until(extended, "card", extension) is None


@pytest.mark.parametrize("states,result", [([], "release"), (["declined"], "release"),
    (["declined", "declined"], "release"), (["pending"], "hold"), (["held"], "hold"),
    (["declined", "pending"], "hold"), (["confirmed"], "hold")])
def test_attempt_aware_expiry(states, result):
    assert clock.expiry_decision(order(), [{"state": s} for s in states], START + timedelta(hours=48)) == result
    assert clock.expiry_decision(order(), [{"state": s} for s in states], START + timedelta(hours=47)) == "wait"


def test_changing_route_cannot_revive_elapsed_selected_window():
    selected = order(payment_method="card", deadline=START + timedelta(hours=24))
    assert not clock.can_initiate(selected, "omt", START + timedelta(hours=25))


def test_released_or_paid_never_expire_again():
    for state in ("expired_released", "paid_held", "awaiting_notification"):
        assert clock.expiry_decision(order(state=state), [], START + timedelta(days=10)) == "wait"
    assert clock.expiry_decision(order(currency="LBP"), [], START + timedelta(days=10)) == "hold"
