import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from bt_contracts.catalog.listings.eligibility import PublicationEligibility
from bt_contracts.catalog.listings.v1 import WatchFacts, incomplete

ROOT = Path(__file__).resolve().parents[4]
FIXTURES = json.loads((ROOT / "packages/contracts-catalog/listings/fixtures/eligibility-v1.json").read_text())


def test_success_is_listing_specific():
    assert PublicationEligibility.model_validate(FIXTURES["success"]).reviewed


@pytest.mark.parametrize("change", [
    {"proof_listing_id": "00000000-0000-4000-8000-000000000009"},
    {"proof_watch_id": "00000000-0000-4000-8000-000000000009"},
    {"proof_identity_digest": "b" * 64},
    {"proof_revision": None}, {"reviewed": False},
    {"single_use_code_consumed": False},
    {"proof_submitted_at": "2026-11-15T23:59:59Z"},
    {"proof_submitted_at": "2026-11-17T00:00:00Z"},
    {"proof_submitted_at": "2026-11-17T00:00:01Z"},
    {"code_issued_at": "2026-11-16T00:00:00"},
    {"proof_revision": True}, {"current": "true"},
    {"private_bytes": "excluded"},
])
def test_unreviewed_cross_listing_stale_and_boundary_proof(change):
    with pytest.raises(ValidationError):
        PublicationEligibility.model_validate({**FIXTURES["success"], **change})


def test_issue_instant_is_inclusive():
    value = {**FIXTURES["success"], "proof_submitted_at": "2026-11-16T00:00:00Z"}
    assert PublicationEligibility.model_validate(value).reviewed


@pytest.mark.parametrize("included,no_documents,valid", [
    ([], True, True), (["papers"], False, True),
    (["papers"], True, False), ([], False, False),
])
def test_explicit_document_declaration(included, no_documents, valid):
    result = incomplete(WatchFacts(included=included, no_documents=no_documents), 1)
    assert ("no_documents" not in result) == valid


def test_normalization_removes_metadata():
    import io
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    spec = importlib.util.spec_from_file_location("listing_images", ROOT / "services/catalog/modules/media/images.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = io.BytesIO()
    metadata = PngInfo()
    metadata.add_text("serial", "private-synthetic-reference")
    Image.new("RGB", (40, 20)).save(source, format="PNG", pnginfo=metadata)
    for variant in module.normalize(source.getvalue()).values():
        assert b"private-synthetic-reference" not in variant["content"]
        with Image.open(io.BytesIO(variant["content"])) as image:
            assert not image.getexif()
            assert not image.info.get("comment")
            assert image.size == (40, 20)


@pytest.mark.parametrize("case,code", [
    ("pending", "publication_review_pending"),
    ("denied", "publication_review_denied"),
    ("stale", "publication_review_pending"),
    ("lost_response", "publication_review_pending"),
    ("duplicate", "publication_review_pending"),
])
def test_consumer_denies_uncertain_stale_and_duplicate_cases(case, code):
    from modules.listings.eligibility import require_eligible
    from bt_contracts_core.errors import PublicError

    binding = {key: FIXTURES["success"][key] for key in (
        "schema_version", "operation_id", "subject_id", "listing_id", "watch_id", "actor_id",
        "organization_id", "expected_revision", "identity_digest",
    )}
    require_eligible(FIXTURES["success"], binding)
    with pytest.raises(PublicError) as failure:
        require_eligible(FIXTURES[case], binding)
    assert failure.value.code == code


@pytest.mark.parametrize("field,value", [
    ("subject_id", "00000000-0000-4000-8000-000000000009"),
    ("actor_id", "00000000-0000-4000-8000-000000000009"),
    ("operation_id", "different-operation"),
    ("current", False),
])
def test_consumer_rechecks_current_scope(field, value):
    from modules.listings.eligibility import require_eligible
    from bt_contracts_core.errors import PublicError

    binding = {key: FIXTURES["success"][key] for key in (
        "schema_version", "operation_id", "subject_id", "listing_id", "watch_id", "actor_id",
        "organization_id", "expected_revision", "identity_digest",
    )}
    with pytest.raises(PublicError):
        require_eligible({**FIXTURES["success"], field: value}, binding)


@pytest.mark.parametrize("case", ["at_bytes", "over_bytes", "over_pixels", "unsupported", "animated"])
def test_public_image_limits(monkeypatch, case):
    import io
    from PIL import Image
    from bt_contracts_core.errors import PublicError

    spec = importlib.util.spec_from_file_location("bounded_listing_images", ROOT / "services/catalog/modules/media/images.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = io.BytesIO()
    image = Image.new("RGB", (40, 20))
    if case == "animated":
        image.save(source, format="PNG", save_all=True, append_images=[Image.new("RGB", (40, 20), "red")], duration=100)
    else:
        image.save(source, format="GIF" if case == "unsupported" else "PNG")
    content = source.getvalue()
    if case in ("at_bytes", "over_bytes"):
        monkeypatch.setattr(module, "MAX_BYTES", len(content) - (case == "over_bytes"))
    if case == "over_pixels":
        monkeypatch.setattr(module, "MAX_PIXELS", 799)
    if case == "at_bytes":
        assert module.normalize(content)["detail"]["width"] == 40
    else:
        with pytest.raises(PublicError):
            module.normalize(content)


@pytest.mark.parametrize("field", ["subject_id", "revision", "pending_reason", "next_actor", "next_review_at"])
def test_stable_envelope_fields_are_required(field):
    value = {key: item for key, item in FIXTURES["success"].items() if key != field}
    with pytest.raises(ValidationError):
        PublicationEligibility.model_validate(value)


@pytest.mark.parametrize("change", [
    {"revision": True}, {"revision": 0}, {"next_actor": None},
    {"next_actor": " "}, {"pending_reason": None}, {"pending_reason": ""},
    {"next_review_at": None}, {"next_review_at": "2026-11-17T12:00:00"},
])
def test_pending_requires_valid_recovery_envelope(change):
    with pytest.raises(ValidationError):
        PublicationEligibility.model_validate({**FIXTURES["pending"], **change})


def test_pending_preserves_responsible_role_review_time_and_operation():
    from modules.listings.eligibility import require_eligible
    from bt_contracts_core.errors import PublicError

    binding = {key: FIXTURES["success"][key] for key in (
        "schema_version", "operation_id", "subject_id", "listing_id", "watch_id",
        "actor_id", "organization_id", "expected_revision", "identity_digest",
    )}
    with pytest.raises(PublicError) as failure:
        require_eligible(FIXTURES["pending"], binding)
    assert failure.value.code == "publication_review_pending"
    assert failure.value.details == {key: FIXTURES["pending"][key] for key in (
        "operation_id", "subject_id", "revision", "pending_reason", "next_actor", "next_review_at",
    )}


@pytest.mark.asyncio
async def test_publication_request_binds_subject_without_guessing_decision_revision(monkeypatch):
    from modules.listings import eligibility

    expected = FIXTURES["success"]
    row = {"id": expected["listing_id"], "physical_watch_id": expected["watch_id"],
           "organization_id": None, "revision": 1, "facts": {}}
    monkeypatch.setattr(eligibility, "identity_digest", lambda actual: expected["identity_digest"])

    async def response(request, service, method, path, **kwargs):
        assert service == "identity" and method == "POST"
        assert path == "/internal/v1/listing-eligibility/validate"
        assert kwargs["headers"] == {"Idempotency-Key": expected["operation_id"]}
        assert kwargs["json"]["subject_id"] == row["id"]
        assert kwargs["json"]["expected_revision"] == row["revision"]
        assert "revision" not in kwargs["json"]
        return {**expected, "revision": 7}

    monkeypatch.setattr(eligibility, "service_request", response)
    await eligibility.check_publication(None, row, expected["operation_id"], expected["actor_id"])
