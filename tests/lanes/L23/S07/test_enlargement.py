import copy
import importlib.util
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[4]
DIRECTORY = ROOT / "services/service-operations/modules/enlargement"
spec = importlib.util.spec_from_file_location("enlargement_service", DIRECTORY / "__init__.py", submodule_search_locations=[str(DIRECTORY)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
Service, Rejected = module.Service, module.Rejected
module = sys.modules["enlargement_service.service"]
BUYER = "10000000-0000-4000-8000-000000000001"
ORG = "10000000-0000-4000-8000-000000000002"
WATCH = "10000000-0000-4000-8000-000000000003"
REQUEST = "10000000-0000-4000-8000-000000000004"
NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)

@pytest.fixture
def setup(tmp_path):
    facts = dict(active=True, authorized=True, actor_id=BUYER, buyer_id=BUYER,
        organization_id=ORG, watch_id=WATCH, source_revision=1, role="buyer",
        assignment_current=True, commitment_current=True, capability_current=True,
        quote_current=True, explicit_lines_accepted=True,
        accepted_scope_current=True, custody_current=True, paid_held=True,
        approval_current=True, independence_current=True, quality_current=True,
        incident_open=False, approver_id="approver",
        responsible_operator_id="operator-1", next_action={"en":"Confirm compatible parts", "ar":"تأكيد القطع المتوافقة"},
        next_review_at="2026-11-18T00:00:00Z")
    path = tmp_path / "state.db"
    service = Service(path, lambda actor, body: facts, lambda: NOW)
    return service, facts, path

def command(kind="request", revision=0, operation="request_0001", payload=None):
    return dict(schema_version="enlargement.v1", operation_id=operation,
        request_id=REQUEST, watch_id=WATCH, organization_id=ORG,
        expected_revision=revision, source_revision=1, kind=kind,
        payload=payload if payload is not None else dict(measurement="17.5",unit="cm",method="tape",source="buyer",target="Comfortable fit",choice="links"))

def assess(service, facts, status="available"):
    service.execute(BUYER, command())
    facts.update(actor_id="assessor", role="assessor")
    part = dict(id="actual-link",revision=7,kind="links",status=status,quantity=2)
    facts["parts"] = {part["id"]:part}
    quote = dict(quote_id="quote-1",quote_revision=3,total_minor=50000,
        expires_at="2026-11-17T00:15:00Z",terms_revision=2)
    facts["quote"] = dict(**quote,currency="USD",base_minor=50000,buyer_fee_minor=0,business_fee_minor=2500,buyer_id=BUYER,request_id=REQUEST,lines=[dict(id="line-1",label_en="Compatible links and fitting",label_ar="وصلات متوافقة وتركيب",amount_minor=50000)],terms={"en":"Accepted job terms","ar":"شروط الخدمة المقبولة"})
    return service.execute("assessor", command("assess",1,"assessment_0001",dict(**quote,parts=[part],target="Actual fit assessment",limitations="No other intervention")))

def accept(service, facts):
    facts.update(actor_id=BUYER,role="buyer")
    return service.execute(BUYER,command("accept",2,"acceptance_0001",dict(quote_id="quote-1",quote_revision=3,terms_revision=2,accepted_line_ids=["line-1"])))

def test_exact_measurement():
    assert module.measurement("17.5","cm") == "175"
    assert module.measurement("175","mm") == "175"


@pytest.mark.parametrize("field", ["base_minor", "buyer_fee_minor", "business_fee_minor", "total_minor"])
@pytest.mark.parametrize("invalid", ["float", "boolean", "negative", "overflow", "missing"])
def test_retained_money_requires_bounded_integers_without_advancement(setup, field, invalid):
    service, facts, _ = setup
    result = assess(service, facts)
    tables = ("l23_enlargement_records", "l23_enlargement_receipts", "l23_enlargement_outbox")
    def snapshot():
        with service.connect() as db:
            return [db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in tables]
    before = snapshot()
    if invalid == "missing":
        facts["quote"].pop(field)
    else:
        facts["quote"][field] = {
            "float": float(facts["quote"][field]),
            "boolean": False,
            "negative": -1,
            "overflow": 10**12 + 1,
        }[invalid]
    with pytest.raises(Rejected, match="money"):
        service.execute("assessor", command("assess", 2, "assessment_0002", result["assessment"]))
    assert snapshot() == before

@pytest.mark.parametrize("value",["17,5","17.55","NaN","0","999","1e2"])
def test_bad_measurement(value):
    with pytest.raises(Rejected): module.measurement(value,"cm")

def test_restart_and_lost_response(setup):
    service, facts, path = setup
    result = service.execute(BUYER,command())
    restarted = Service(path,lambda actor,body:facts,lambda:NOW)
    assert restarted.execute(BUYER,command()) == result
    with restarted.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM l23_enlargement_outbox").fetchone()[0] == 1
    changed = command(); changed["payload"]["target"] = "Different"
    with pytest.raises(Rejected,match="operation_conflict"): restarted.execute(BUYER,changed)

def test_revocation_denies_duplicate(setup):
    service,facts,_ = setup
    service.execute(BUYER,command()); facts["authorized"] = False
    with pytest.raises(Rejected,match="denied"): service.execute(BUYER,command())

@pytest.mark.parametrize("field,value,code",[("organization_id",WATCH,"denied"),("watch_id",ORG,"denied"),("source_revision",2,"stale"),("commitment_current",False,"unavailable"),("capability_current",False,"unavailable")])
def test_current_facts(setup,field,value,code):
    service,facts,_ = setup; facts[field]=value
    with pytest.raises(Rejected,match=code): service.execute(BUYER,command())

def test_timeout_is_not_success(setup):
    service,_,_ = setup
    def timeout(actor,body): raise TimeoutError()
    service.current=timeout
    with pytest.raises(Rejected,match="unavailable"):service.execute(BUYER,command())
    with service.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM l23_enlargement_records").fetchone()[0] == 0

@pytest.mark.parametrize("status",["ordered","unavailable"])
def test_missing_parts_wait_and_cannot_complete(setup,status):
    service,facts,_ = setup
    result=assess(service,facts,status)
    assert result["state"] == "waiting" and result["next_review_at"]
    with pytest.raises(Rejected,match="state"): accept(service,facts)

@pytest.mark.parametrize("delta,accepted",[(-1,True),(0,False),(1,False)])
def test_accept_expiry_boundaries(setup,delta,accepted):
    service,facts,_=setup; assess(service,facts)
    service.clock=lambda: NOW+timedelta(minutes=15,seconds=delta)
    if accepted: assert accept(service,facts)["state"] == "accepted"
    else:
        with pytest.raises(Rejected,match="expired"):accept(service,facts)

@pytest.mark.parametrize("field",["accepted_scope_current","custody_current","paid_held","approval_current","independence_current"])
def test_work_requires_current_prerequisites(setup,field):
    service,facts,_=setup;assess(service,facts);accept(service,facts)
    facts.update(actor_id="staff",role="staff");facts[field]=False
    with pytest.raises(Rejected,match="work_held"):
        service.execute("staff",command("work",3,"work_0001",dict(performed="Two compatible links fitted",part_ids=["actual-link"],completed_line_ids=["line-1"])))

def test_actual_work_and_independent_fit(setup):
    service,facts,_=setup;assess(service,facts);accept(service,facts)
    facts.update(actor_id="staff",role="staff")
    result=service.execute("staff",command("work",3,"work_0001",dict(performed="Two compatible links fitted",part_ids=["actual-link"],completed_line_ids=["line-1"])))
    assert result["state"] == "worked"
    payload=dict(fit="Comfortable",tests="Clasp secure",returned_parts="None",passed=True,work_revision=4)
    facts.update(actor_id="assessor",role="quality")
    with pytest.raises(Rejected,match="denied"): service.execute("assessor",command("fit",4,"quality_0001",payload))
    facts.update(actor_id="quality",role="quality")
    assert service.execute("quality",command("fit",4,"quality_0001",payload))["state"] == "fit_recorded"

def test_no_invented_adjustment_fields(setup):
    service,_,_=setup
    for key in ("links_per_cm","fixed5mm","stretch_metal"):
        body=command();body["payload"][key]=True
        with pytest.raises(Rejected,match="scope"):service.execute(BUYER,body)

def test_stale_and_cross_account(setup):
    service,facts,_=setup;service.execute(BUYER,command())
    with pytest.raises(Rejected,match="stale"):service.execute(BUYER,command(operation="request_0002"))
    facts.update(actor_id="other",buyer_id="other")
    with pytest.raises(Rejected,match="denied"):service.execute("other",command())


def test_read_revocation_and_reassignment(setup):
    service,facts,_=setup
    service.execute(BUYER,command())
    facts.update(role="staff",actor_id="staff",assignment_current=False)
    with pytest.raises(Rejected,match="denied"): service.read("staff",REQUEST)
    facts.update(role="buyer",actor_id=BUYER,authorized=False)
    with pytest.raises(Rejected,match="denied"): service.read(BUYER,REQUEST)


def test_duplicate_rechecks_staff_assignment(setup):
    service,facts,_=setup;assess(service,facts)
    facts["assignment_current"]=False
    with pytest.raises(Rejected,match="denied"):
        service.execute("assessor",command("assess",1,"assessment_0001",{}))


def test_provider_deadline_and_bounded_admission(setup):
    from threading import Event
    service,facts,path=setup
    release=Event()
    def blocked(actor,body):
        release.wait(1)
        return facts
    service=Service(path,blocked,lambda:NOW,dependency_timeout=0.01)
    try:
        with pytest.raises(Rejected,match="unavailable"):service.execute(BUYER,command())
        with pytest.raises(Rejected,match="unavailable"):service.execute(BUYER,command())
    finally: release.set()


def test_missing_required_line_cannot_complete(setup):
    service,facts,_=setup;assess(service,facts);accept(service,facts)
    facts.update(actor_id="staff",role="staff")
    with pytest.raises(Rejected,match="work_missing"):
        service.execute("staff",command("work",3,"work_0001",dict(performed="Only partial work",part_ids=["actual-link"],completed_line_ids=[])))


def test_outbox_has_no_private_notes(setup):
    service,facts,_=setup;service.execute(BUYER,command())
    with service.connect() as db:
        event=db.execute("SELECT body FROM l23_enlargement_outbox").fetchone()[0]
        assert "Comfortable" not in event and "buyer" not in event and "tape" not in event


def test_versioned_fixtures_are_replayable(tmp_path):
    import json
    fixture=json.loads((ROOT / 'packages/contracts-service/enlargement/fixtures.json').read_text())
    success=fixture['success']
    service=Service(tmp_path/'fixtures.db',lambda actor,body:success['facts'],lambda:NOW)
    assert service.execute(success['actor_id'],success['command']) == success['response']
    lost=fixture['lost_response']
    assert service.execute(lost['actor_id'],lost['command']) == lost['response']
    for name in ('denied','stale'):
        example=fixture[name]
        service.current=lambda actor,body:example['facts']
        with pytest.raises(Rejected,match=example['response']['code']):
            service.execute(example['actor_id'],example['command'])


def test_lost_parts_after_acceptance_returns_waiting(setup):
    service,facts,_=setup;assess(service,facts);accept(service,facts)
    facts.update(actor_id="staff",role="staff")
    facts["parts"]["actual-link"]["status"]="unavailable"
    result=service.execute("staff",command("work",3,"work_0001",dict(performed="Not performed",part_ids=["actual-link"],completed_line_ids=["line-1"])))
    assert result["state"] == "waiting"
    assert "work" not in result


def test_failed_quality_requires_rework_and_new_check(setup):
    service,facts,_=setup;assess(service,facts);accept(service,facts)
    facts.update(actor_id="staff",role="staff")
    work=dict(performed="Actual fitting",part_ids=["actual-link"],completed_line_ids=["line-1"])
    service.execute("staff",command("work",3,"work_0001",work))
    facts.update(actor_id="quality",role="quality")
    quality=dict(fit="Too loose",tests="Clasp tested",returned_parts="None",passed=False,work_revision=4)
    assert service.execute("quality",command("fit",4,"quality_0001",quality))["state"] == "rework"
    facts.update(actor_id="staff",role="staff")
    revised=service.execute("staff",command("work",5,"work_0002",work))
    assert revised["state"] == "worked" and "quality" not in revised
    facts.update(actor_id="quality",role="quality")
    quality.update(passed=True,fit="Comfortable",work_revision=6)
    assert service.execute("quality",command("fit",6,"quality_0002",quality))["state"] == "fit_recorded"


def test_adapter_rejects_invalid_input_without_private_detail(setup):
    from enlargement_service.adapter import command_response, read_response
    service,facts,_=setup
    invalid=command();invalid["payload"]["measurement"]="private invalid value"
    assert command_response(service,BUYER,invalid) == (422,{"code":"measurement"})
    assert command_response(service,BUYER,{}) == (422,{"code":"invalid_input"})
    assert read_response(service,BUYER,REQUEST) == (403,{"code":"denied"})


@pytest.mark.parametrize("quantity", [0, 1, None, True, "2"])
def test_insufficient_current_quantity_cannot_complete(setup, quantity):
    service, facts, _ = setup
    assess(service, facts)
    accept(service, facts)
    facts.update(actor_id="staff", role="staff")
    facts["parts"]["actual-link"]["quantity"] = quantity
    result = service.execute("staff", command("work", 3, "work_0001", dict(
        performed="Fitting", part_ids=["actual-link"], completed_line_ids=["line-1"])))
    assert result["state"] == "waiting"
    assert "work" not in result


@pytest.mark.parametrize("quantity", [2, 3])
def test_sufficient_current_quantity_allows_work(setup, quantity):
    service, facts, _ = setup
    assess(service, facts)
    accept(service, facts)
    facts.update(actor_id="staff", role="staff")
    facts["parts"]["actual-link"]["quantity"] = quantity
    result = service.execute("staff", command("work", 3, "work_0001", dict(
        performed="Fitting", part_ids=["actual-link"], completed_line_ids=["line-1"])))
    assert result["state"] == "worked"


def test_duplicate_part_rows_cannot_reuse_available_quantity(setup):
    service, facts, _ = setup
    result = assess(service, facts)
    payload = copy.deepcopy(result["assessment"])
    payload["parts"].append(copy.deepcopy(payload["parts"][0]))
    with pytest.raises(Rejected, match="parts"):
        service.execute("assessor", command("assess", 2, "assessment_0002", payload))


@pytest.mark.parametrize('state', ['accepted', 'worked', 'rework'])
def test_changed_scope_requires_renewed_acceptance(setup, state):
    service, facts, _ = setup
    assessment = assess(service, facts)['assessment']
    accept(service, facts)
    revision = 3
    if state in ('worked', 'rework'):
        facts.update(actor_id='staff', role='staff')
        service.execute('staff', command('work', 3, 'work_0001', dict(
            performed='Actual fitting', part_ids=['actual-link'], completed_line_ids=['line-1'])))
        revision = 4
    if state == 'rework':
        facts.update(actor_id='quality', role='quality')
        service.execute('quality', command('fit', 4, 'quality_0001', dict(
            fit='Too loose', tests='Checked', returned_parts='None', passed=False, work_revision=4)))
        revision = 5
    facts.update(actor_id='assessor', role='assessor')
    assert 'assess' in service.read('assessor', REQUEST)['allowed_operations']
    changed = copy.deepcopy(assessment)
    changed['target'] = 'Revised fit'
    result = service.execute('assessor', command('assess', revision, 'assessment_0002', changed))
    assert result['state'] == 'assessed'
    assert not {'accepted', 'work', 'work_revision', 'quality'} & result.keys()
    facts.update(actor_id='staff', role='staff')
    with pytest.raises(Rejected, match='state'):
        service.execute('staff', command('work', revision + 1, 'work_0002', {}))
    facts.update(actor_id=BUYER, role='buyer')
    accepted = service.execute(BUYER, command('accept', revision + 1, 'acceptance_0002', dict(
        quote_id='quote-1', quote_revision=3, terms_revision=2, accepted_line_ids=['line-1'])))
    assert accepted['state'] == 'accepted'


def test_waiting_retains_owner_action_and_deadlines_after_restart(setup):
    service, facts, path = setup
    result = assess(service, facts, 'ordered')
    assert result['responsible_operator_id'] == 'operator-1'
    assert result['next_action'] == facts['next_action']
    assert result['first_response_due_at'] == '2026-11-18T00:00:00Z'
    assert result['escalation_at'] == '2026-11-19T00:00:00Z'
    restarted = Service(path, lambda actor, body: facts, lambda: NOW + timedelta(minutes=5))
    refreshed = restarted.execute('assessor', command('assess', 2, 'assessment_0002', result['assessment']))
    for field in ('waiting_since', 'first_response_due_at', 'escalation_at'):
        assert refreshed[field] == result[field]


@pytest.mark.parametrize('field', ['responsible_operator_id', 'next_action'])
def test_waiting_requires_current_responsibility(setup, field):
    service, facts, _ = setup
    facts.pop(field)
    with pytest.raises(Rejected):
        assess(service, facts, 'unavailable')
    with service.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM l23_enlargement_receipts').fetchone()[0] == 1


@pytest.mark.parametrize('seconds,allowed', [(-1, True), (0, True), (1, False)])
def test_waiting_first_review_boundary(setup, seconds, allowed):
    service, facts, _ = setup
    facts['next_review_at'] = (NOW + timedelta(hours=24, seconds=seconds)).isoformat().replace('+00:00', 'Z')
    if allowed:
        assert assess(service, facts, 'ordered')['state'] == 'waiting'
    else:
        with pytest.raises(Rejected, match='review_required'):
            assess(service, facts, 'ordered')


@pytest.mark.parametrize('seconds', [-1, 0, 1])
def test_overdue_waiting_followup_preserves_original_boundaries(setup, seconds):
    service, facts, _ = setup
    result = assess(service, facts, 'ordered')
    later = NOW + timedelta(hours=24, seconds=seconds)
    service.clock = lambda: later
    payload = copy.deepcopy(result['assessment'])
    payload['expires_at'] = (later + timedelta(minutes=15)).isoformat().replace('+00:00', 'Z')
    facts['quote']['expires_at'] = payload['expires_at']
    facts['next_review_at'] = (later + timedelta(hours=24)).isoformat().replace('+00:00', 'Z')
    updated = service.execute('assessor', command('assess', 2, 'assessment_0002', payload))
    assert updated['state'] == 'waiting'
    for field in ('waiting_since', 'first_response_due_at', 'escalation_at'):
        assert updated[field] == result[field]
    assert updated['next_review_at'] == facts['next_review_at']


def prepare_quality(service, facts):
    assess(service, facts)
    accept(service, facts)
    facts.update(actor_id='staff', role='staff')
    service.execute('staff', command('work', 3, 'work_0001', dict(
        performed='Actual fitting', part_ids=['actual-link'], completed_line_ids=['line-1'])))
    facts.update(actor_id='quality', role='quality')
    return command('fit', 4, 'quality_0001', dict(
        fit='Too loose', tests='Checked', returned_parts='None', passed=False, work_revision=4))


@pytest.mark.parametrize('seconds,allowed', [(-1, True), (0, True), (1, False)])
def test_rework_review_boundary_and_restart(setup, seconds, allowed):
    service, facts, path = setup
    body = prepare_quality(service, facts)
    facts['next_review_at'] = (NOW + timedelta(hours=24, seconds=seconds)).isoformat().replace('+00:00', 'Z')
    if not allowed:
        with pytest.raises(Rejected, match='review_required'):
            service.execute('quality', body)
        assert service.read('quality', REQUEST)['state'] == 'worked'
        return
    result = service.execute('quality', body)
    assert result['state'] == 'rework'
    assert result['responsible_operator_id'] == facts['responsible_operator_id']
    assert result['next_action'] == facts['next_action']
    assert result['pending_reason'] == 'rework'
    for hours in (24, 48):
        for delta in (-1, 0, 1):
            restarted = Service(path, lambda actor, body: facts,
                lambda: NOW + timedelta(hours=hours, seconds=delta))
            retained = restarted.read('quality', REQUEST)
            assert retained['first_response_due_at'] == '2026-11-18T00:00:00Z'
            assert retained['escalation_at'] == '2026-11-19T00:00:00Z'
            assert restarted.execute('quality', body) == result


@pytest.mark.parametrize('field', ['responsible_operator_id', 'next_action', 'next_review_at'])
def test_rework_requires_responsibility(setup, field):
    service, facts, _ = setup
    body = prepare_quality(service, facts)
    facts.pop(field)
    with pytest.raises(Rejected):
        service.execute('quality', body)
    assert service.read('quality', REQUEST)['state'] == 'worked'
