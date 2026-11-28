"""Local lane admission substitute until shared runtime composition is widened."""
import re

import pytest


@pytest.fixture(autouse=True)
def lane_admission(monkeypatch):
    from bt_runtime import modules

    monkeypatch.setattr(modules, 'MODULE_ID', re.compile(r'^L(0[1-9]|1[0-9]|2[0-5])\.[a-z][a-z0-9.-]+$'))
    monkeypatch.setattr(modules, 'MIGRATION', re.compile(r'^L(0[1-9]|1[0-9]|2[0-5])_[0-9]{4}_[a-z0-9_]+\.sql$'))
