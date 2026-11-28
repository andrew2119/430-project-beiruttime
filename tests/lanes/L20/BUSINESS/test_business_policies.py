import importlib.util
from importlib.resources import files
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
import service_app

RUNTIME = Path(service_app.__file__).resolve().parent.parent
MODULES = RUNTIME / 'modules'
if not MODULES.is_dir():
    ROOT = RUNTIME.parents[2]
    MODULES = RUNTIME.parent / 'modules'
    CONTRACTS = ROOT / 'packages/contracts-identity/businesses'
else:
    CONTRACTS = files('bt_contracts.identity.businesses')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


p = load("possession_policy", MODULES / "private-review/possession.py")
s = load("staff_policy", MODULES / "membership/administration.py")
c = load("capability_policy", MODULES / "businesses/capabilities.py")
v = load("business_contract_v2", CONTRACTS / "current_v2.py")
SELLER, WATCH, REVIEWER, OTHER, BUSINESS, ADMIN, CHALLENGE, PHOTO = [UUID(int=i) for i in range(1, 9)]
NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)
FACTS = p.ListingFacts(SELLER, WATCH, 1, 1, True)


@pytest.fixture
def issued():
    return p.issue(FACTS, SELLER, CHALLENGE, "123456", NOW)


@pytest.fixture
def pending(issued):
    return p.submit(issued, FACTS, SELLER, 1, CHALLENGE, "١٢٣٤٥٦", PHOTO,
                    NOW + timedelta(hours=1), evidence_owned=True)


@pytest.fixture
def assigned(pending):
    return p.assign(pending, FACTS, 2, REVIEWER, operator_permitted=True,
                    reviewer_qualified=True)


def test_possession_positive(assigned):
    approved = p.decide(assigned, FACTS, REVIEWER, 3, 1, "approved", "Photo and code checked",
                        reviewer_qualified=True)
    assert p.publication_allowed(approved, FACTS)
    assert approved.code_digest == ""
    assert not p.publication_allowed(assigned, FACTS)
    assert not p.publication_allowed(approved, replace(FACTS, listing_revision=2))
    assert not p.publication_allowed(approved, replace(FACTS, watch_revision=2))
    assert not p.publication_allowed(approved, replace(FACTS, seller_approved=False))


@pytest.mark.parametrize("elapsed", [timedelta(hours=24), timedelta(days=2), timedelta(seconds=-1)])
def test_submission_deadline(issued, elapsed):
    with pytest.raises(p.PossessionDenied, match="proof_expired"):
        p.submit(issued, FACTS, SELLER, 1, CHALLENGE, "123456", PHOTO,
                 NOW + elapsed, evidence_owned=True)


@pytest.mark.parametrize("actor,owned,code", [(OTHER, True, "123456"),
    (SELLER, False, "123456"), (SELLER, True, "123457")])
def test_submission_denials(issued, actor, owned, code):
    with pytest.raises(p.PossessionDenied):
        p.submit(issued, FACTS, actor, 1, CHALLENGE, code, PHOTO, NOW, evidence_owned=owned)


def test_submission_single_use(pending):
    with pytest.raises(p.PossessionDenied, match="single_use_code"):
        p.submit(pending, FACTS, SELLER, 2, CHALLENGE, "123456", PHOTO, NOW, evidence_owned=True)


@pytest.mark.parametrize("operator,qualified,reviewer", [(False, True, REVIEWER),
    (True, False, REVIEWER), (True, True, SELLER)])
def test_independent_assignment(pending, operator, qualified, reviewer):
    with pytest.raises(p.PossessionDenied):
        p.assign(pending, FACTS, 2, reviewer, operator_permitted=operator,
                 reviewer_qualified=qualified)


def test_reassignment_removes_evidence(assigned):
    reassigned = p.assign(assigned, FACTS, 3, OTHER, operator_permitted=True, reviewer_qualified=True)
    with pytest.raises(p.PossessionDenied):
        p.read_evidence(reassigned, FACTS, REVIEWER, reviewer_qualified=True)
    assert p.read_evidence(reassigned, FACTS, OTHER, reviewer_qualified=True) == PHOTO
    with pytest.raises(p.PossessionDenied, match="stale_assignment"):
        p.decide(reassigned, FACTS, OTHER, 4, 1, "approved", "Checked the private photo",
                 reviewer_qualified=True)


@pytest.mark.parametrize("revision,facts,qualified", [(2, FACTS, True),
    (3, replace(FACTS, watch_revision=2), True), (3, FACTS, False)])
def test_review_current_authority(assigned, revision, facts, qualified):
    with pytest.raises(p.PossessionDenied):
        p.decide(assigned, facts, REVIEWER, revision, 1, "approved", "Checked private photo",
                 reviewer_qualified=qualified)


@pytest.mark.parametrize("verdict", ["correction", "rejected", "suspended"])
def test_nonapproval(assigned, verdict):
    result = p.decide(assigned, FACTS, REVIEWER, 3, 1, verdict, "Evidence needs correction",
                      reviewer_qualified=True)
    assert not p.publication_allowed(result, FACTS)


@pytest.fixture
def authority():
    return s.Administration(s.Member(ADMIN, BUSINESS, frozenset({"business.staff.manage"})),
                            BUSINESS, True, s.ORDINARY, 2)


def change(authority, **overrides):
    params = dict(subject_id=SELLER, business_id=BUSINESS, expected_revision=0,
                  kind="grant", permissions={"business.jobs.write"}, reason="Ordinary staff grant",
                  responsibilities_current=True)
    params.update(overrides)
    return s.change(authority, **params)


def test_staff_positive_and_replacement(authority):
    member = change(authority).member
    job = s.Job(WATCH, BUSINESS, SELLER, 4)
    replacement = s.Member(OTHER, BUSINESS, frozenset({"business.jobs.write"}))
    result = change(authority, existing=member, expected_revision=1, kind="suspend",
                    permissions=(), jobs=(job,), replacement=replacement)
    assert result.member.state == "suspended"
    assert result.jobs[0].responsible_id == OTHER
    assert result.jobs[0].revision == 5
    assert member.state == "active" and job.responsible_id == SELLER


@pytest.mark.parametrize("permission", ["business.staff.manage", "identity.membership.manage",
    "identity.private-seller.review", "unknown"])
def test_no_privileged_grants(authority, permission):
    with pytest.raises(s.AdministrationDenied, match="platform_ceiling_exceeded"):
        change(authority, permissions={permission})


@pytest.mark.parametrize("update", [dict(subject_id=ADMIN), dict(business_id=OTHER),
    dict(expected_revision=1), dict(responsibilities_current=False)])
def test_staff_denials(authority, update):
    with pytest.raises(s.AdministrationDenied):
        change(authority, **update)


@pytest.mark.parametrize("field,value", [("business_active", False),
    ("ceiling", frozenset()), ("actor", s.Member(ADMIN, BUSINESS, frozenset(), state="suspended"))])
def test_revoked_or_ceiling(authority, field, value):
    with pytest.raises(s.AdministrationDenied):
        change(replace(authority, **{field: value}))


@pytest.mark.parametrize("kind,permissions", [("suspend", ()), ("remove", ()),
    ("grant", ("business.records.read",))])
def test_job_cannot_be_abandoned(authority, kind, permissions):
    member = change(authority).member
    with pytest.raises(s.AdministrationDenied, match="responsible_replacement_required"):
        change(authority, existing=member, expected_revision=1, kind=kind,
                permissions=permissions, jobs=(s.Job(WATCH, BUSINESS, SELLER, 1),))


def test_privileged_target_denied(authority):
    with pytest.raises(s.AdministrationDenied, match="privileged_membership_denied"):
        change(authority, existing=s.Member(SELLER, BUSINESS, frozenset({"business.staff.manage"})),
                expected_revision=1, kind="remove", permissions=())


def test_synthetic_declaration():
    declaration = c.CapabilityDeclaration(BUSINESS, 1, frozenset({"sales"}), True)
    assert declaration.permits(BUSINESS, 1, {"sales"}, synthetic_release=True)
    assert not declaration.permits(BUSINESS, 1, {"sales"}, synthetic_release=False)
    assert not declaration.permits(BUSINESS, 2, {"sales"}, synthetic_release=True)
    real = replace(declaration, synthetic=False)
    assert not real.permits(BUSINESS, 1, {"sales"}, synthetic_release=False)
    real = replace(real, confirmation_ref=PHOTO, confirmed_scope=frozenset({"sales"}))
    assert real.permits(BUSINESS, 1, {"sales"}, synthetic_release=False)
    assert not real.permits(BUSINESS, 1, {"servicing"}, synthetic_release=False)


def test_contract_normalization_and_unknown_fields():
    command = dict(operation_id=CHALLENGE, subject_id=SELLER, actor_id=SELLER,
                   expected_revision=0, kind="submit", watch_id=WATCH, watch_revision=1,
                   listing_revision=1, challenge_id=CHALLENGE, code="١٢٣٤٥٦", evidence_ref=PHOTO)
    assert v.PossessionCommand(**command).code == "123456"
    with pytest.raises(ValueError):
        v.PossessionCommand(**command, public_evidence=True)
    with pytest.raises(ValueError):
        v.StaffCommand(ceiling_revision=2, operation_id=CHALLENGE, subject_id=SELLER, actor_id=ADMIN,
                       organization_id=BUSINESS, expected_revision=0, kind="grant", reason="     ")


r = load("business_receipts", MODULES / "membership/command_receipts.py")


class ReceiptTx:
    def __init__(self):
        self.receipt = None
        self.applied = 0

    async def execute(self, sql, *args):
        if "INSERT INTO" in sql:
            self.receipt = {"fingerprint": args[6], "result": args[7]}

    async def fetchrow(self, sql, *args):
        return self.receipt


@pytest.mark.asyncio
async def test_duplicate_lost_response_recovery_and_conflict():
    tx = ReceiptTx()
    command = v.StaffCommand(ceiling_revision=2, operation_id=CHALLENGE, actor_id=ADMIN, subject_id=SELLER,
                             organization_id=BUSINESS, expected_revision=0,
                             kind="grant", reason="Ordinary colleague")
    checks = []

    async def authorize(tx, command):
        checks.append(command.actor_id)

    async def apply(tx, command):
        tx.applied += 1
        return {"revision": 1, "state": "active"}

    first = await r.execute(tx, command, authorize=authorize, apply=apply)
    # Discarding the response does not create another transition on retry.
    recovered = await r.execute(tx, command, authorize=authorize, apply=apply)
    assert recovered == first and tx.applied == 1 and len(checks) == 2
    with pytest.raises(r.ReceiptConflict):
        await r.execute(tx, command.model_copy(update={"reason": "Different colleague reason"}),
                        authorize=authorize, apply=apply)
    assert tx.applied == 1

    async def revoked(tx, command):
        raise PermissionError("Current permission required")

    with pytest.raises(PermissionError):
        await r.execute(tx, command, authorize=revoked, apply=apply)


@pytest.mark.asyncio
async def test_unavailable_never_records_success():
    tx = ReceiptTx()
    command = v.StaffCommand(ceiling_revision=2, operation_id=CHALLENGE, actor_id=ADMIN, subject_id=SELLER,
                             organization_id=BUSINESS, expected_revision=0,
                             kind="grant", reason="Ordinary colleague")

    async def unavailable(tx, command):
        raise TimeoutError("responsibilities_unavailable")

    async def apply(tx, command):
        tx.applied += 1

    with pytest.raises(TimeoutError):
        await r.execute(tx, command, authorize=unavailable, apply=apply)
    assert tx.receipt is None and tx.applied == 0


@pytest.mark.parametrize("state", ["pending", "approved", "suspended"])
def test_existing_proof_cannot_be_overwritten(issued, state):
    protected = replace(issued, state=state)
    with pytest.raises(p.PossessionDenied, match="existing_proof_protected"):
        p.issue(FACTS, SELLER, OTHER, "654321", NOW, existing=protected)
    fresh = p.issue(replace(FACTS, listing_revision=2), SELLER, OTHER, "654321", NOW,
                    existing=protected)
    assert fresh.facts.listing_revision == 2 and not p.publication_allowed(fresh, fresh.facts)


@pytest.mark.parametrize("state", ["correction", "rejected"])
def test_correction_recovery_uses_new_code(issued, state):
    corrected = p.issue(FACTS, SELLER, OTHER, "654321", NOW, existing=replace(issued, state=state))
    with pytest.raises(p.PossessionDenied, match="invalid_code"):
        p.submit(corrected, FACTS, SELLER, corrected.revision, CHALLENGE, "123456", PHOTO, NOW,
                 evidence_owned=True)
    assert p.submit(corrected, FACTS, SELLER, corrected.revision, OTHER, "654321", PHOTO, NOW,
                     evidence_owned=True).state == "pending"


@pytest.mark.parametrize("kind,fields", [("submit", {}), ("assign", {}), ("decide", {})])
def test_command_requires_operation_fields(kind, fields):
    with pytest.raises(ValueError):
        v.PossessionCommand(operation_id=CHALLENGE, subject_id=SELLER, actor_id=SELLER,
                             expected_revision=0, kind=kind, watch_id=WATCH,
                             watch_revision=1, listing_revision=1, **fields)


def test_deterministic_contract_fixtures():
    import json
    fixtures = json.loads((CONTRACTS / "fixtures/commands.v2.json").read_text())
    assert {row["name"] for row in fixtures} == {"success", "denied", "stale", "lost-response", "timeout"}
    for row in fixtures:
        assert row["synthetic"] is True
        v.StaffCommand(**row["command"])



def test_expired_challenge_recovery(issued):
    recovered = p.issue(FACTS, SELLER, OTHER, "654321", NOW + timedelta(hours=24), existing=issued)
    assert recovered.issued_at == NOW + timedelta(hours=24)
    assert p.submit(recovered, FACTS, SELLER, recovered.revision, OTHER, "654321", PHOTO,
                     recovered.issued_at, evidence_owned=True).state == "pending"



def test_prior_generation_decision_cannot_approve_new_photo(assigned):
    correction = p.decide(assigned, FACTS, REVIEWER, 3, 1, "correction", "A clearer photo is required",
                           reviewer_qualified=True)
    fresh = p.issue(FACTS, SELLER, OTHER, "654321", NOW, existing=correction)
    submitted = p.submit(fresh, FACTS, SELLER, fresh.revision, OTHER, "654321", CHALLENGE,
                          NOW, evidence_owned=True)
    reassigned = p.assign(submitted, FACTS, submitted.revision, REVIEWER,
                           operator_permitted=True, reviewer_qualified=True)
    assert reassigned.revision > assigned.revision
    assert reassigned.assignment_revision > assigned.assignment_revision
    with pytest.raises(p.PossessionDenied, match="stale_revision"):
        p.decide(reassigned, FACTS, REVIEWER, assigned.revision, assigned.assignment_revision,
                  "approved", "Old photo had been checked", reviewer_qualified=True)


@pytest.mark.parametrize('changes', [
    {'state': 'suspended'}, {'state': 'revoked'}, {'capabilities': []},
    {'qualifications': []}, {'intervention_scope': 'A different scope'},
])
def test_legacy_membership_requires_responsibility_boundary(changes):
    from types import SimpleNamespace
    row = dict(capabilities=['business.jobs.write'], qualifications=['Intake'], intervention_scope='Current scope')
    body = dict(state='active', capabilities=None, qualifications=None, intervention_scope=None)
    body.update(changes)
    assert s.responsibility_reducing(row, SimpleNamespace(**body))


def test_legacy_membership_preserves_responsibility():
    from types import SimpleNamespace
    row = dict(capabilities=['business.jobs.write'], qualifications=['Intake'], intervention_scope='Current scope')
    body = SimpleNamespace(state='active', capabilities=['business.jobs.write', 'business.records.read'], qualifications=None, intervention_scope=None)
    assert not s.responsibility_reducing(row, body)


@pytest.mark.parametrize("kind", ["suspend", "remove"])
def test_lowered_ceiling_still_allows_removal_with_replacement(authority, kind):
    member = s.Member(SELLER, BUSINESS, s.ORDINARY)
    reduced = replace(authority, ceiling=frozenset({"business.records.read"}), ceiling_revision=3)
    params = dict(existing=member, expected_revision=1, kind=kind,
                  permissions=member.permissions, jobs=(s.Job(WATCH, BUSINESS, SELLER, 4),))
    with pytest.raises(s.AdministrationDenied, match="responsible_replacement_required"):
        change(reduced, **params)
    replacement = s.Member(OTHER, BUSINESS, frozenset({"business.jobs.write"}))
    result = change(reduced, replacement=replacement, **params)
    assert result.member.state == {"suspend": "suspended", "remove": "revoked"}[kind]
    assert result.jobs[0].responsible_id == OTHER
    assert result.jobs[0].revision == 5
    with pytest.raises(s.AdministrationDenied, match="platform_ceiling_exceeded"):
        change(reduced, existing=member, expected_revision=1, permissions=member.permissions)
