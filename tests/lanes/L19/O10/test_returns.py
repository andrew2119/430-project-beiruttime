import importlib.util
import sys
from pathlib import Path
from dataclasses import replace
import pytest

ROOT = Path(__file__).resolve().parents[4]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
Command = load('returns_contract', 'packages/contracts-orders/returns/v1.py').Command
Returns = load('returns_store', 'services/orders/modules/returns/store.py').Returns

@pytest.fixture
def setup(tmp_path):
    facts = dict(authorized=True, organization_id='shop', watch_id='watch', policy_revision='p1', revision=7, buyer_id='buyer', paid_held=True, assigned_reviewer=True, assigned_intake=True, financial_producer=False, principal_minor=500000, currency='USD', quote_id='quote', quote_revision=1, subject_id='order', actor_id='buyer', accessories=['box'], watch_revision=2, responsible_operator='operator', next_review_at='2026-11-18T00:00:00Z', now='2026-11-17T00:00:00Z')
    def source(actor, organization, subject, timeout_seconds):
        assert timeout_seconds == 2
        return dict(facts, actor_id=actor)
    path = tmp_path / 'returns.db'
    store = Returns(path, source)
    command = Command('request','order','watch','buyer','shop',0,'request',7,'p1','Policy review')
    yield store, facts, command, path, source
    store.close()

def permit(store, c):
    assert store.execute(c)['state'] == 'requested'
    p = replace(c, operation_id='permit', actor_id='reviewer', expected_revision=1, kind='permit')
    assert store.execute(p)['state'] == 'permitted'
    return replace(p, operation_id='receive', actor_id='intake', expected_revision=2, kind='receive', receipt_id='receipt')

def receipt(f):
    f['receipt'] = dict(receipt_id='receipt', order_id='order', watch_id='watch', watch_revision=2, authorized_recipient='intake', to_actor='intake', from_actor='buyer', condition='scratched', location='intake', proof_revision=1, incident_revision=0, accessories=['box'], received_at=f['now'])

def test_restart_duplicate_and_handoff(setup):
    s,f,c,path,source = setup
    r = permit(s,c); receipt(f)
    result = s.execute(r)
    assert result['state'] == 'received'
    restarted = Returns(path,source)
    assert restarted.execute(r) == result
    assert restarted.lookup('receive','intake','shop','order') == result
    assert restarted.db.execute('SELECT count(*) FROM l19_outbox').fetchone()[0] == 1
    with pytest.raises(ValueError,match='operation_conflict'):
        restarted.execute(replace(r, reason='Different'))
    f['authorized'] = False
    with pytest.raises(ValueError,match='denied'):
        restarted.execute(r)
    restarted.close()

@pytest.mark.parametrize('change', ['watch','accessories','absent','future'])
def test_unresolved(setup,change):
    s,f,c,_,_ = setup
    r=permit(s,c); receipt(f)
    if change=='watch': f['receipt']['watch_id']='other'
    if change=='accessories': f['receipt']['accessories']=[]
    if change=='absent': f['receipt']=None
    if change=='future': f['receipt']['received_at']='2026-11-17T00:00:01Z'
    assert s.execute(r)['state']=='unresolved'
    assert s.db.execute('SELECT count(*) FROM l19_outbox').fetchone()[0]==0

@pytest.mark.parametrize('change,error', [('revision','stale_revision'),('organization','denied'),('actor','denied')])
def test_denied_and_stale(setup,change,error):
    s,f,c,_,_=setup
    if change=='revision': c=replace(c,expected_revision=1)
    if change=='organization': c=replace(c,organization_id='other')
    if change=='actor': c=replace(c,actor_id='other')
    with pytest.raises(ValueError,match=error): s.execute(c)
    assert s.db.execute('SELECT count(*) FROM l19_operations').fetchone()[0]==0

def test_timeout_retry(setup):
    s,f,c,_,source=setup
    def unavailable(*args,**kwargs): raise TimeoutError()
    s.source=unavailable
    with pytest.raises(ValueError,match='unavailable'): s.execute(c)
    s.source=source
    assert s.execute(c)['state']=='requested'

@pytest.mark.parametrize('offset', [-1,0,1])
def test_receipt_boundary(setup,offset):
    s,f,c,_,_=setup
    r=permit(s,c); receipt(f)
    f['receipt']['received_at']={-1:'2026-11-16T23:59:59Z',0:f['now'],1:'2026-11-17T00:00:01Z'}[offset]
    assert s.execute(r)['state']==('unresolved' if offset>0 else 'received')

def test_financial_producer_only(setup):
    s,f,c,_,_=setup
    r=permit(s,c);receipt(f);s.execute(r)
    refund=replace(r,operation_id='refund',kind='refunded',expected_revision=3)
    with pytest.raises(ValueError,match='denied'):s.execute(refund)
    f.update(financial_producer=True,refund_state='refunded',refund_return_operation='receive')
    assert s.execute(refund)['state']=='refunded'

@pytest.mark.parametrize('key,value', [('watch_id','another'),('quote_id','another'),('quote_revision',2),('principal_minor',1),('policy_revision','p2')])
def test_retained_bindings(setup,key,value):
    s,f,c,_,_=setup
    r=permit(s,c)
    f[key]=value
    if key=='watch_id':r=replace(r,watch_id=value)
    if key=='policy_revision':r=replace(r,policy_revision=value)
    with pytest.raises(ValueError,match='stale_source'):s.execute(r)

def test_private_current_and_cross_subject(setup):
    s,f,c,_,_=setup
    s.execute(c)
    assert s.current('buyer','shop','order')['state']=='requested'
    with pytest.raises(ValueError,match='denied'):s.current('buyer','shop','other')
    f['authorized']=False
    with pytest.raises(ValueError,match='denied'):s.current('buyer','shop','order')

def test_contract_fixtures(tmp_path):
    import json
    cases=json.loads((ROOT/'packages/contracts-orders/returns/fixtures.json').read_text())['cases']
    for i,case in enumerate(cases):
        facts=case['source']
        def source(actor, organization, subject, timeout_seconds):return facts
        s=Returns(tmp_path/f'fixture-{i}.db',source)
        command=Command(**case['command'])
        if 'error' in case['result']:
            with pytest.raises(ValueError,match=case['result']['error']):s.execute(command)
        else:
            assert s.execute(command)==case['result']
            if case['name']=='lost_response':assert s.execute(command)==case['result']
        s.close()


@pytest.mark.parametrize('value', ['x' * 129, None, 42])
def test_receipt_reference_validation_precedes_persistence(setup, value):
    s, f, c, _, _ = setup
    r = permit(s, c)
    receipt(f)
    f['receipt']['receipt_id'] = value
    invalid = replace(r, receipt_id=value)
    with pytest.raises(ValueError, match='invalid'):
        invalid.validate()
    with pytest.raises(ValueError, match='invalid'):
        s.execute(invalid)
    assert s.current('buyer', 'shop', 'order')['state'] == 'permitted'
    assert s.lookup('receive', 'intake', 'shop', 'order') is None
    assert s.db.execute('SELECT count(*) FROM l19_outbox').fetchone()[0] == 0
