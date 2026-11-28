import importlib.util
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location('signal_core', ROOT / 'services/trust/modules/fraud-signals/core.py')
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)
NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def command(**changes):
    return dict(schema_version='fraud-signals.v1', operation_id='operation-0001', subject_id='subject',
                watch_id='watch', organization_id='business', expected_revision=0, source_revision=1, **changes)


def context(**changes):
    return dict(actor_id='reviewer', organization_id='business', subject_id='subject', watch_id='watch',
                source_revision=1, record_revision=0, assigned=True, permitted=True, seller_id='seller',
                parties=['subject', 'seller', 'bidder'], valid_until=NOW+timedelta(seconds=1), **changes)


def photo(watch='watch', digest='a'*64, id='photo'):
    return dict(photo_id=id, normalized_hash=digest, normalization_version='v1', watch_id=watch, seller_id='seller')


def bid(auction, at=NOW, automatic=False, seller='seller', id=None):
    return dict(bid_id=id or auction, auction_id=auction, bidder_id='bidder', seller_id=seller,
                accepted_at=at.isoformat(), automatic=automatic)


def test_photo_reuse_is_only_review_and_private(tmp_path):
    store=core.Store(tmp_path/'signals.db')
    result=store.scan(command(),context(),[photo(),photo('other',id='other')],[],NOW)
    assert result['state']=='review_required'
    assert result['reasons']==[{'kind':'exact_photo_reuse','count':1}]
    assert not any(key in str(result) for key in ['normalized_hash','bidder','ban','forfeit'])
    assert result['next_actor']=='reviewer'
    assert result['next_review_at']=='2026-11-18T00:00:00+00:00'
    store.close()


@pytest.mark.parametrize('photos', [[],[photo()],[photo(),photo(id='second')],[photo(),photo('other','b'*64,'other')]])
def test_negative_photos(photos):
    assert core.detect(photos,[],'watch',NOW,'seller')==[]


@pytest.mark.parametrize('offset,expected', [(-1,False),(0,True),(1,True)])
def test_window_start(offset,expected):
    bids=[bid('a'),bid('b'),bid('c',NOW-timedelta(days=30)+timedelta(seconds=offset))]
    assert bool(core.detect([],bids,'watch',NOW,'seller')) is expected


def test_pair_distinct_auctions_and_manual_only():
    assert core.detect([],[bid('a'),bid('a',id='second'),bid('b',automatic=True)],'watch',NOW,'seller')==[]
    assert core.detect([],[bid('a',seller='other'),bid('b',seller='other'),bid('c',seller='other')],'watch',NOW,'seller')==[]
    assert core.detect([],[bid('a'),bid('b'),bid('c')],'watch',NOW,'seller')==[{'kind':'repeated_pair','count':1}]


def test_future_and_conflicting_source_denied():
    with pytest.raises(core.Rejected):
        core.detect([],[bid('a',NOW+timedelta(seconds=1))],'watch',NOW,'seller')
    with pytest.raises(core.Rejected):
        core.detect([photo(),photo('other')],[],'watch',NOW,'seller')


@pytest.mark.parametrize('field,value', [('organization_id','other'),('assigned',False),('permitted',False),('actor_id','seller'),('valid_until',NOW)])
def test_current_authority(tmp_path,field,value):
    store=core.Store(tmp_path/'signals.db')
    current=context();current[field]=value
    with pytest.raises(core.Rejected):store.scan(command(),current,[],[],NOW)
    assert store.db.execute('SELECT count(*) FROM l19_signal_operations').fetchone()[0]==0
    store.close()


def test_restart_replay_conflict_stale_and_revocation(tmp_path):
    path=tmp_path/'signals.db'
    store=core.Store(path)
    result=store.scan(command(),context(),[],[],NOW)
    store.close();store=core.Store(path)
    assert store.scan(command(),context(),[],[],NOW)==result
    assert store.lookup('operation-0001',context(),NOW)==result
    changed=command();changed['expected_revision']=1
    with pytest.raises(core.Rejected,match='conflict'):store.scan(changed,context(),[],[],NOW)
    changed['operation_id']='operation-0002';changed['expected_revision']=0
    with pytest.raises(core.Rejected,match='stale'):store.scan(changed,context(),[],[],NOW)
    denied=context();denied['permitted']=False
    with pytest.raises(core.Rejected,match='denied'):store.lookup('operation-0001',denied,NOW)
    current=context();current['source_revision']=2
    with pytest.raises(core.Rejected,match='stale'):store.scan(command(),current,[],[],NOW)
    current=context();current['actor_id']='other-reviewer'
    with pytest.raises(core.Rejected,match='denied'):store.scan(command(),current,[],[],NOW)
    store.close()


def test_bounds_and_atomic_rollback(tmp_path):
    store=core.Store(tmp_path/'signals.db')
    with pytest.raises(core.Rejected,match='invalid'):store.scan(command(),context(),[photo()]*501,[],NOW)
    assert store.page(context(),NOW)['total']==0
    assert store.scan(command(),context(),[],[],NOW)['revision']==1
    with pytest.raises(core.Rejected):store.page(context(),NOW,page_size=51)
    store.close()


def test_thousand_rows_have_real_pagination(tmp_path):
    store=core.Store(tmp_path/'signals.db')
    for n in range(1000):
        body=command();body.update(operation_id=f'operation-{n:04}',expected_revision=n)
        current=context();current['record_revision']=n
        store.scan(body,current,[],[],NOW)
    result=store.page(context(),NOW,page=50)
    assert result['total']==1000 and len(result['items'])==20
    assert result['items'][-1]['operation_id']=='operation-0999'
    assert store.page(context(),NOW,page=51)['items']==[]
    store.close()


def test_published_contract_fixtures(tmp_path):
    import json
    fixture=json.loads((ROOT/'packages/contracts-trust/fraud-signals/fixtures.json').read_text())
    store=core.Store(tmp_path/'signals.db')
    result=store.scan(fixture['request'],context(),fixture['photos'],fixture['bids'],NOW)
    assert result==fixture['success']
    assert store.lookup(fixture['request']['operation_id'],context(),NOW)==fixture['lost_response']['result']
    for name in ['denied','stale']:
        current=context();current.update(fixture[name]['context_override'])
        with pytest.raises(core.Rejected,match=fixture[name]['body']['detail']['code']):
            store.scan(fixture['request'],current,fixture['photos'],fixture['bids'],NOW)
    store.close()
    store=core.Store(tmp_path/'negative.db')
    assert store.scan(fixture['request'],context(),[],[],NOW)==fixture['negative']
    store.close()


@pytest.mark.parametrize('change', [
    {'parties': None}, {'parties': []}, {'parties': 'subject,seller'},
    {'parties': ['subject']}, {'parties': ['seller']},
    {'parties': ['subject', 'seller', None]},
    {'seller_id': None}, {'subject_id': ''}, {'actor_id': 'seller'},
])
def test_incomplete_independence_denies_every_access(tmp_path, change):
    store = core.Store(tmp_path / 'signals.db')
    store.scan(command(), context(), [], [], NOW)
    current = context()
    current.update(change)
    if change == {'parties': None}:
        del current['parties']
    for action in (
        lambda: store.scan(command(), current, [], [], NOW),
        lambda: store.lookup('operation-0001', current, NOW),
        lambda: store.page(current, NOW),
    ):
        with pytest.raises(core.Rejected, match='denied'):
            action()
    fresh = command()
    fresh.update(operation_id='operation-0002', expected_revision=1)
    with pytest.raises(core.Rejected, match='denied'):
        store.scan(fresh, current, [], [], NOW)
    assert store.page(context(), NOW)['total'] == 1
    store.close()


def test_source_bidder_missing_from_independence_facts_denied(tmp_path):
    store = core.Store(tmp_path / 'signals.db')
    current = context()
    current['parties'] = ['subject', 'seller']
    with pytest.raises(core.Rejected, match='denied'):
        store.scan(command(), current, [], [bid('auction')], NOW)
    assert store.page(context(), NOW)['total'] == 0
    store.close()
