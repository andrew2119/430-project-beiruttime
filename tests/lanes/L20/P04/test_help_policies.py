import asyncio
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[4]
MODULE = ROOT / "services/communications/modules/help-policies"
CONTRACT = ROOT / "packages/contracts-comms/help-policies"
spec = importlib.util.spec_from_file_location("help_policies", MODULE / "__init__.py", submodule_search_locations=[str(MODULE)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
from help_policies.current import Artifact, Authority, Request, read_accepted  # noqa: E402
from help_policies.routes import ReadContext, create_router  # noqa: E402

NOW = datetime(2026, 11, 16, 10, tzinfo=timezone.utc)
REQUEST = Request("sample-read-1", "sample-person-1", None, "sample-person-1", "sample-watch-1", "sample-record-1", 1)
SCHEMA = json.loads((CONTRACT / "accepted-terms.v1.schema.json").read_text())
def validate(answer):
    assert set(answer) == set(SCHEMA["required"])
    assert answer["schema_version"] == "help-policies.v1"
    assert answer["state"] in SCHEMA["properties"]["state"]["enum"]
    if answer["state"] == "ready":
        assert answer["artifact"]["issuer"] == "E03"
        assert answer["artifact"]["en"] and answer["artifact"]["ar"]
    else:
        assert answer["artifact"] is None


class Provider:
    def __init__(self):
        self.authority = Authority(True, 1, "access-1")
        self.artifact = Artifact(REQUEST, "sample-policy-1", "2026-11-16T10:00:00Z", "Synthetic accepted policy text.", "نص شروط مقبول تجريبي.")
        self.calls = 0
        self.change = None
        self.fail = None

    async def authorize(self, request):
        return self.authority

    async def accepted_terms(self, request):
        self.calls += 1
        if self.fail:
            raise self.fail
        if self.change:
            self.authority = self.change
        return self.artifact


def read(provider, request=REQUEST, now=NOW):
    answer = asyncio.run(read_accepted(request, provider, now))
    validate(answer)
    return answer


def test_ready_duplicate_and_restart_preserve_original_artifact():
    provider = Provider()
    first = read(provider)
    assert first["state"] == "ready"
    assert read(provider) == first
    assert read(Provider()) == first
    assert first["artifact"]["policy_revision"] == "sample-policy-1"


@pytest.mark.parametrize("allowed,revision,state", [(False, 1, "denied"), (True, 2, "stale")])
def test_current_authority_before_provider(allowed, revision, state):
    provider = Provider()
    provider.authority = Authority(allowed, revision, "access-1")
    assert read(provider)["state"] == state
    assert provider.calls == 0


@pytest.mark.parametrize("change,state", [(Authority(False, 1, "access-1"), "denied"), (Authority(True, 1, "access-2"), "denied"), (Authority(True, 2, "access-1"), "stale")])
def test_current_authority_after_provider(change, state):
    provider = Provider()
    provider.change = change
    answer = read(provider)
    assert answer["state"] == state
    assert answer["artifact"] is None


@pytest.mark.parametrize("field,value", [("organization_id", "other-business"), ("actor_id", "other-person"), ("subject_id", "other-person"), ("watch_id", "other-watch"), ("record_id", "other-record"), ("operation_id", "other-operation")])
def test_cross_scope_artifact_denied(field, value):
    assert read(Provider(), replace(REQUEST, **{field:value}))["state"] == "denied"


def test_missing_pending_and_lost_response_recovery():
    assert read(None)["state"] == "unavailable"
    provider = Provider()
    provider.artifact = None
    assert read(provider)["state"] == "pending"
    provider = Provider()
    provider.fail = TimeoutError()
    assert read(provider)["state"] == "unavailable"
    assert provider.calls == 1
    provider.fail = None
    assert read(provider)["state"] == "ready"


def test_real_timeout_is_bounded():
    class Slow(Provider):
        async def accepted_terms(self, request):
            await asyncio.sleep(10)
    assert read(Slow())["state"] == "unavailable"


@pytest.mark.parametrize("seconds,state", [(-1, "ready"), (0, "unavailable"), (1, "unavailable")])
def test_available_until_before_equal_after(seconds, state):
    provider = Provider()
    provider.artifact = replace(provider.artifact, accepted_at="2026-11-15T10:00:00Z", available_until=NOW.isoformat())
    assert read(provider, now=NOW + timedelta(seconds=seconds))["state"] == state


@pytest.mark.parametrize("accepted", ["2026-11-16T10:00:00", "2026-11-16T12:00:00+02:00", "2026-11-16T10:00:01Z"])
def test_invalid_or_future_time(accepted):
    provider = Provider()
    provider.artifact = replace(provider.artifact, accepted_at=accepted)
    assert read(provider)["state"] == "unavailable"


@pytest.mark.parametrize("revision", [True, 0, -1, 1.5])
def test_invalid_revision(revision):
    with pytest.raises(ValueError):
        replace(REQUEST, expected_revision=revision)


def test_bounds_and_private_text_validation():
    with pytest.raises(ValueError):
        replace(REQUEST, operation_id="x" * 129)
    provider = Provider()
    provider.artifact = replace(provider.artifact, ar=" ")
    assert read(provider)["state"] == "unavailable"


def test_fixtures_match_response_envelope():
    for fixture in json.loads((CONTRACT / "fixtures.v1.json").read_text()).values():
        validate(fixture)


def test_public_route_without_identity_and_private_no_store():
    provider = Provider()
    async def context():
        return ReadContext(REQUEST.actor_id, None, REQUEST.subject_id, REQUEST.watch_id, provider)
    app = FastAPI()
    app.include_router(create_router(json.loads((CONTRACT / "guidance.v1.json").read_text()), context))
    async def exercise():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            public = await client.get("/v1/help-policies")
            assert public.status_code == 200
            assert len(public.json()["articles"]) == 13
            assert provider.calls == 0
            response = await client.get("/v1/help-policies/accepted-terms/sample-record-1?expected_revision=1", headers={"Operation-Id":"sample-read-1"})
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            invalid = await client.get("/v1/help-policies/accepted-terms/sample-record-1?expected_revision=0")
            assert invalid.status_code == 422
    asyncio.run(exercise())


def test_bilingual_complete_content_and_exact_commercial_facts():
    doc = json.loads((CONTRACT / "guidance.v1.json").read_text())
    ids = [article["id"] for article in doc["articles"]]
    assert len(ids) == len(set(ids))
    for article in doc["articles"]:
        for locale in ("en", "ar"):
            assert article[locale]["title"] and article[locale]["body"]
    text = {article["id"]:article["en"]["body"] for article in doc["articles"]}
    for amount in ("$5,000", "$5,150", "$250", "$4,750"):
        assert amount in text["fees"]
    assert "72 hours" in text["returns"] and "168 hours" in text["returns"]
    assert "Whish Money" in text["payments"] and "OMT Pay" in text["payments"]
    assert "no actual insurance" in text["failed-inspection"]
    assert "unavailable" in text["support"] and "E03" in text["terms"]


def test_deadline_rechecked_after_dependency_and_private_exception_is_hidden():
    provider = Provider()
    provider.artifact = replace(provider.artifact, available_until="2026-11-16T10:00:01Z")
    times = iter([NOW, NOW + timedelta(seconds=1)])
    assert read(provider, now=lambda: next(times))["state"] == "unavailable"
    provider.fail = RuntimeError("restricted evidence must not escape")
    result = read(provider)
    assert result["state"] == "unavailable"
    assert "restricted evidence" not in str(result)
