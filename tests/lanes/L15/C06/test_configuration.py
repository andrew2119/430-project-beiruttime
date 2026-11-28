"""Exact source boundaries without a connected database."""
import asyncio
import importlib.util
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from bt_contracts_core.errors import PublicError

ROOT = Path(__file__).resolve().parents[4]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = load("configuration_contract", "packages/contracts-catalog/configuration/v1.py")
validation = load("configuration_validation", "services/catalog/runtime/service_app/configuration.py")
KINDS = validation.DIMENSIONS
BRAND = UUID(int=100)
IDS = {kind: UUID(int=index + 1) for index, kind in enumerate(KINDS)}
MOUNTING = {"case": "case", "dial": "dial", "hands": "hands", "functions": []}


class Source:
    def __init__(self, change=None, rule=None):
        self.change = change or {}
        self.rule = rule

    async def fetchrow(self, query, *args):
        if "catalog_compatibility_rules" in query:
            return self.rule
        kind = "movement" if "movement_options" in query else args[1]
        row = {"revision": 1, "brand_id": BRAND, "active": True, "caliber": "caliber",
               "cases": ["case"], "dials": ["dial"], "hands": ["hands"], "functions": [],
               "label_en": "Synthetic movement", "label_ar": "حركة تجريبية",
               "quote_minor": 12345, "currency": "USD",
               "definition": {"base_models": ["base"], "calibers": ["caliber"], "available": True}}
        row.update(self.change.get(kind, {}))
        return row


def run(source, chosen=None):
    return asyncio.run(validation.selections(
        source, brand_id=BRAND, base_model="base", caliber="caliber",
        chosen=chosen if chosen is not None else {
            kind: {"option_id": IDS[kind], "option_revision": 1} for kind in KINDS},
        mounting=MOUNTING))


def test_no_rule_is_manual_and_digest_is_deterministic():
    first = run(Source())
    assert first == run(Source())
    assert first["status"] == "manual_assessment"
    assert first["physical_feasibility_pass"] is False
    assert first["price_acceptance"] is False


@pytest.mark.parametrize("status", ["valid", "incompatible", "parts_unavailable", "manual_assessment"])
def test_exact_rule_states(status):
    result = run(Source(rule={"id": UUID(int=90), "revision": 2, "reason": "Declared scope", "status": status}))
    assert result["status"] == status
    assert result["snapshot"]["compatibility_rule"]["revision"] == 2


@pytest.mark.parametrize("change,field,reason", [
    ({"movement": {"brand_id": UUID(int=999)}}, "movement", "other_brand"),
    ({"dial": {"definition": {"base_models": ["other"], "calibers": ["caliber"], "available": True}}}, "dial", "unsupported_base"),
    ({"movement": {"cases": []}}, "movement", "unsupported_mounting"),
])
def test_foreign_or_unsupported_source_never_valid(change, field, reason):
    result = run(Source(change))
    assert result["status"] == "incompatible"
    assert result["fields"][field] == reason


def test_unavailable_part():
    assert run(Source({"movement": {"active": False}}))["status"] == "parts_unavailable"


def test_stale_and_missing_remain_correctable():
    with pytest.raises(PublicError) as stale:
        run(Source({"movement": {"revision": 2}}))
    assert stale.value.code == "configuration_incomplete"
    with pytest.raises(PublicError) as missing:
        run(Source(), {})
    assert missing.value.code == "configuration_incomplete"


def rule():
    return dict(expected_revision=0, base_model="base", caliber="caliber", option_ids=list(IDS.values()),
                option_revisions={key: 1 for key in IDS.values()}, mounting=MOUNTING,
                status="manual_assessment", reason="Review required")


@pytest.mark.parametrize("revision", [0, -1, True, 1.5])
def test_invalid_rule_versions(revision):
    body = rule()
    body["option_revisions"][IDS["dial"]] = revision
    with pytest.raises(ValidationError):
        contract.Rule(**body)


def test_rule_ids_and_versions_must_be_exact():
    body = rule()
    assert contract.Rule(**body).expected_revision == 0
    body["option_ids"][-1] = body["option_ids"][0]
    with pytest.raises(ValidationError):
        contract.Rule(**body)
