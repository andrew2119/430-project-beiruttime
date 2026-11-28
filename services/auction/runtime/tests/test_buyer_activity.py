import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import Response

from bt_contracts_core.errors import PublicError
from bt_runtime.modules import discover
from service_app import buyer_activity
from service_app.buyer_activity import my_bids, activity_page


def test_current_calendar_pages_1000_auctions_and_restarts_at_a_changed_revision():
    buyer = UUID(int=5000)
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    rows = [dict(id=UUID(int=index), listing_id=UUID(int=index + 1000), revision=3,
        starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=2),
        current_minor=0, leader_id=None, listing_is_demo=index % 2 == 0, participated=False)
        for index in range(1, 1001)]
    actor = SimpleNamespace(actor=SimpleNamespace(subject_id=buyer, organization_id=None), roles=['buyer'], organizations=[])

    class Database:
        def transaction(self, **kwargs):
            assert kwargs == {'isolation': 'repeatable_read', 'readonly': True}
            return acquire()

        async def fetchval(self, query):
            assert query == 'SELECT clock_timestamp()'
            return now

        async def fetch(self, query, *args):
            assert "a.currency='USD'" in query and "a.seller_id<>$1" in query
            assert args == (buyer, [], now, 'calendar', 1001)
            return rows

    @asynccontextmanager
    async def acquire():
        yield Database()

    async def principal(request):
        return actor

    runtime = SimpleNamespace(pool=SimpleNamespace(acquire=acquire),
                              auction=SimpleNamespace(dependencies=SimpleNamespace(principal=principal)))
    request = SimpleNamespace(app=SimpleNamespace(state=runtime))

    async def scenarios():
        found = []
        cursor = None
        for index in range(20):
            response = Response()
            page = await my_bids(request, response, view='calendar', limit=50, cursor=cursor)
            assert response.headers['cache-control'] == 'no-store'
            assert page['total'] == 1000 and len(page['items']) == 50
            assert all(row['status'] is None and row['lifecycle'] == 'scheduled' for row in page['items'])
            found.extend(row['auction_id'] for row in page['items'])
            cursor = page['next_cursor']
            if index == 0:
                first = cursor
        assert cursor is None
        assert found == [str(row['id']) for row in rows]
        rows[20]['revision'] += 1
        with pytest.raises(PublicError) as exc:
            await my_bids(request, Response(), view='calendar', limit=50, cursor=first)
        assert exc.value.status == 409 and exc.value.code == 'stale_cursor'
        rows[20]['listing_is_demo'] = None
        with pytest.raises(PublicError) as exc:
            await my_bids(request, Response(), view='calendar', limit=50, cursor=None)
        assert exc.value.status == 503

    asyncio.run(scenarios())


def test_paging_rechecks_buyer_view_membership_and_financial_revision():
    rows = [dict(auction_id=str(UUID(int=index))) for index in range(1, 4)]
    buyer = SimpleNamespace(actor=SimpleNamespace(subject_id=UUID(int=99)), organizations=[])
    cursor = activity_page(rows, buyer, 'released', 1, None, result=True, source_revisions=[('test-order', 2)])['next_cursor']
    assert activity_page(rows, buyer, 'released', 1, cursor, result=True, source_revisions=[('test-order', 2)])['items'] == [rows[1]]
    for actor, view, revision in (
        (buyer, 'unpaid', 2),
        (buyer, 'released', 3),
        (SimpleNamespace(actor=buyer.actor, organizations=[UUID(int=9)]), 'released', 2),
        (SimpleNamespace(actor=SimpleNamespace(subject_id=UUID(int=100)), organizations=[]), 'released', 2),
    ):
        with pytest.raises(PublicError) as exc:
            activity_page(rows, actor, view, 1, cursor, result=True, source_revisions=[('test-order', revision)])
        assert exc.value.status == 409


@pytest.mark.parametrize('view', ['won', 'lost'])
def test_allocation_denial_preserves_standing_and_other_results(monkeypatch, view):
    buyer = UUID(int=70)
    row = dict(id=UUID(int=1), listing_id=UUID(int=2), watch_id=UUID(int=3), currency='USD',
        listing_is_demo=False, result_revision=5, state='allocation_denied', order_id=None,
        closing_minor=450000, winner_id=buyer if view=='won' else UUID(int=72),
        ended_at=datetime(2030, 1, 1, tzinfo=timezone.utc))
    other = dict(row,id=UUID(int=10),listing_id=UUID(int=11),watch_id=UUID(int=12),state='allocation_pending')
    actor = SimpleNamespace(actor=SimpleNamespace(subject_id=buyer,organization_id=None),organizations=[],roles=['buyer'])
    source = next(parent / 'services/auction/modules' for parent in Path(__file__).resolve().parents
                  if (parent / 'services/auction/modules').is_dir())
    module = next(m for m in discover(source) if m.id == 'L16.my-results')
    monkeypatch.setattr(buyer_activity, 'result_rows', AsyncMock(return_value=[row,other]))
    principal = AsyncMock(return_value=actor)
    dependencies = SimpleNamespace(principal=principal, json=AsyncMock())
    state = SimpleNamespace(auction=SimpleNamespace(dependencies=dependencies),
                            hooks={'auction.my-results.project.v2': module.load('projection.py:project')})
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    page = asyncio.run(buyer_activity.my_results(request, Response(), view, limit=50, cursor=None))
    assert page['total'] == 2 and page['state'] == 'available'
    denied, pending = page['items']
    assert denied['state'] == view and denied['allocation_state'] == 'denied'
    assert denied['order_id'] is None and denied['financial_state'] is None and denied['completed_sale'] is False
    assert denied['next_action'] == ('contact_support' if view=='won' else 'view_auction')
    assert pending['state'] == view and 'allocation_state' not in pending
    dependencies.json.assert_not_awaited()


@pytest.mark.parametrize('is_demo,scenario', [
    (False,'normal'), (True,'normal'), (False,'suspended_before'), (True,'suspended_at_fence'),
    (False,'lost_response'), (True,'superseded'), (False,'lost_before_admission'),
    (True,'lost_during_admission'), (False,'lost_org_grant_after_orders'), (True,'changed_session_after_orders'),
    (False,'permanently_revoked'),
])
def test_new_auction_uses_admitted_start_and_catalog_publication(monkeypatch, is_demo, scenario):
    from bt_contracts.auction.core.models import CreateAuction
    from service_app import auction_start, engine, start_recovery
    from service_app.dependencies import Dependencies

    listing, watch, seller, buyer = (UUID(int=index) for index in range(1, 5))
    business = UUID(int=6) if scenario in ('lost_org_grant_after_orders','permanently_revoked') else None
    organization_grants=[SimpleNamespace(organization_id=business,permissions=['identity.listings.publish'])] if business else []
    actor = SimpleNamespace(actor=SimpleNamespace(subject_id=seller, organization_id=business,session_id='test-current'),
                           permissions=['identity.listings.publish'], roles=['private_seller'],
                           organizations=[business] if business else [],organization_grants=organization_grants)
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    command = CreateAuction(listing_id=listing,currency='USD',opening_minor=400000,
                            increment_bands=[dict(from_minor=0,step_minor=10000)],
                            starts_at=now+timedelta(hours=1),ends_at=now+timedelta(hours=2))
    publication = dict(id=str(listing),physical_watch_id=str(watch),seller_id=str(seller),organization_id=str(business) if business else None,
        revision=3,status='published',is_demo=is_demo,facts=dict(currency='USD',sale_mode='auction'),
        registration=dict(listing_id=str(listing),watch_id=str(watch),sale_mode='auction'))
    deps = Dependencies(clients={'catalog': object()})
    deps.json = AsyncMock(return_value=publication)
    deps.principal = AsyncMock(return_value=actor)
    admitted, receipts, commitments, releases, expirations = {}, {}, [], [], []
    inside = False

    async def fence_state(_request, _watch, _listing, auction_id):
        assert not inside
        if not any(intent['auction_id']==str(auction_id) for intent in commitments):
            if scenario=='lost_before_admission':
                actor.permissions.clear()
            return dict(api_version=2,status='available',listing_revision=3,revision=12)
        return dict(api_version=2,status='fenced',listing_revision=3,revision=13,
                    source_kind='auction_open',source_id=str(auction_id),auction_committed=False)

    deps.fence_state = AsyncMock(side_effect=fence_state)

    async def permission(_request, tx, principal):
        assert inside and isinstance(tx, Database) and principal is actor
        if scenario=='suspended_at_fence':
            raise PublicError('bid_permission_required','No new activity.',status=403)
        if scenario=='lost_during_admission':
            actor.permissions.clear()

    async def commit(_request, intent, organization):
        assert not inside and organization==business
        assert any(row['outcome']==intent for row in receipts.values())
        assert intent['code']=='auction_start_pending' and intent['watch_revision']==12
        commitments.append(dict(intent))
        if len(commitments)==1 and scenario in ('lost_response','superseded'):
            actor.permissions.append(engine.SUSPENDED_ACTIVITY)
            if scenario=='lost_response':
                raise auction_start.pending()
            publication['revision']=4
        if len(commitments)==1 and scenario in ('lost_org_grant_after_orders','permanently_revoked'):
            actor.organization_grants=[]
        if len(commitments)==1 and scenario=='changed_session_after_orders':
            actor.actor.session_id='test-changed'
        return {'status':'succeeded','id':str(UUID(int=5))}

    async def release(_request,intent,open_key):
        assert not inside and not admitted and open_key=='auction-open:'+intent['auction_id']
        assert intent['open_operation_id']==str(UUID(int=5)) and intent['release_reason']=='listing_changed'
        assert list(receipts.values())[0]['outcome']==intent
        releases.append(dict(intent))
        if len(releases)==1:
            raise auction_start.pending()

    async def expire(worker_request,intent):
        assert not inside and not admitted and worker_request.headers=={}
        assert intent['code']=='auction_start_expiry_pending' and intent['watch_revision']==12
        expirations.append({key:value for key,value in intent.items() if key!='recovery_after'})
        if len(expirations)==1:
            raise auction_start.pending()

    deps.bid_admission=AsyncMock(side_effect=permission)
    deps.start_commitment=AsyncMock(side_effect=commit)
    deps.expire_start_commitment=AsyncMock(side_effect=expire)
    deps.release_start_commitment=AsyncMock(side_effect=release)
    if scenario=='suspended_before':
        actor.permissions.append(engine.SUSPENDED_ACTIVITY)

    class Database:
        def transaction(self, **kwargs):
            return acquire()

        async def execute(self, query, *args):
            assert inside
            if 'pg_advisory_xact_lock' in query:
                return
            if "outcome->>'release_reason'=$3" in query:
                operation,phase,reason,outcome=args
                row=next(value for value in receipts.values() if value['id']==operation)
                assert row['outcome']['code']==phase and row['outcome']['release_reason']==reason
                row['outcome']=json.loads(outcome)
                return
            if 'INSERT INTO auction_operations' in query:
                operation, subject, organization, key, request_hash, auction_id, outcome = args
                assert (subject,key) not in receipts
                receipts[subject,key]=dict(id=operation,organization_id=organization,request_hash=request_hash,
                    auction_id=auction_id,outcome=json.loads(outcome))
                return
            assert 'UPDATE auction_operations' in query
            operation,outcome=args
            row=next(value for value in receipts.values() if value['id']==operation)
            row['outcome']=json.loads(outcome)

        async def fetchval(self, query, *args):
            if query == 'SELECT clock_timestamp()':
                return now
            if "outcome->>'status'='pending'" in query:
                return any(row['outcome']['status']=='pending' for row in receipts.values())
            return None

        async def fetchrow(self, query, *args):
            if "'recovery_after',clock_timestamp()" in query:
                operation,subject,key=args
                row=receipts[subject,key]
                assert row['id']==operation and now>=command.ends_at and 'start_deadline' in query
                row['outcome'].update(code='auction_start_expiry_pending',release_reason='schedule_ended',recovery_after='later')
                return dict(auction_id=row['auction_id'],outcome=json.dumps(row['outcome']))
            if 'FROM auction_operations' in query:
                return receipts.get(args)
            if 'INSERT INTO auction_lots' not in query:
                assert 'FROM auction_lots' in query
                return admitted or None
            assert 'listing_is_demo' in query and args[-1] is is_demo
            admitted.update(id=args[0],listing_id=args[1],watch_id=args[2],listing_is_demo=args[-1],opening_minor=args[6],
                current_minor=0,revision=1,starts_at=args[9],ends_at=args[10],increment_bands=[dict(from_minor=0,step_minor=10000)],
                leader_id=None,accepted_sequence=0,high_value_minor=args[12],currency='USD',reserve_minor=None,
                rules_version='ordinary.v1',extension_policy='none.v1',participated=False)
            return admitted

        async def fetch(self, query, *args):
            assert 'a.listing_is_demo' in query and args[0]==buyer
            return [admitted]

    @asynccontextmanager
    async def acquire():
        yield Database()

    @asynccontextmanager
    async def transaction(_pool, *, lock_key=None):
        nonlocal inside
        if lock_key is not None:
            assert lock_key==f'operation:{seller}:test-published'
        assert not inside
        inside=True
        try:
            yield Database()
        finally:
            inside=False

    enqueue=AsyncMock()
    monkeypatch.setattr(auction_start,'unit_of_work',transaction)
    monkeypatch.setattr(start_recovery,'unit_of_work',transaction)
    monkeypatch.setattr(auction_start,'enqueue',enqueue)
    admission = engine.AuctionEngine(deps)
    request = SimpleNamespace(headers={'idempotency-key':'test-published'},state=SimpleNamespace(request_id='test-request'),
        app=SimpleNamespace(state=SimpleNamespace(auction=admission,pool=SimpleNamespace(acquire=acquire))))

    async def run():
        nonlocal now
        if scenario=='permanently_revoked':
            with pytest.raises(PublicError,match='sale_mode_pending'):
                await admission.create(request,command)
            with pytest.raises(engine.AccessDenied):
                await admission.create(request,command)
            assert not admitted and len(commitments)==1
            original=receipts[seller,'test-published']
            now=command.ends_at+timedelta(seconds=1)
            candidate=dict(id=original['id'],subject_id=seller,operation_key='test-published')
            lookup_count=deps.principal.await_count
            with pytest.raises(PublicError,match='sale_mode_pending'):
                await start_recovery.recover_start(request.app,candidate)
            assert original['outcome']['status']=='pending' and deps.principal.await_count==lookup_count
            # Another authorized seller for the business can start only after exact settlement.
            actor.actor.subject_id=buyer
            actor.organization_grants=organization_grants
            request.headers['idempotency-key']='test-colleague'
            replacement=command.model_copy(update={'starts_at':now+timedelta(minutes=1),'ends_at':now+timedelta(hours=1)})
            with pytest.raises(PublicError,match='sale_mode_pending'):
                await admission.create(request,replacement)
            lookup_count=deps.principal.await_count
            await start_recovery.recover_start(request.app,candidate)
            assert original['outcome']['status']=='denied' and original['outcome']['code']=='schedule_ended'
            assert deps.principal.await_count==lookup_count and expirations[0]==expirations[1]
            assert not admitted and len(commitments)==1
            result=await admission.create(request,replacement)
            assert result['status']=='succeeded' and result['auction_id']!=original['outcome']['auction_id']
            return
        if scenario in ('lost_before_admission','lost_during_admission'):
            with pytest.raises(engine.AccessDenied):
                await admission.create(request,command)
            assert not admitted and not receipts and not commitments
            enqueue.assert_not_awaited()
            assert deps.bid_admission.await_count==int(scenario=='lost_during_admission')
            return
        if scenario in ('lost_response','superseded','lost_org_grant_after_orders','changed_session_after_orders'):
            with pytest.raises(PublicError,match='sale_mode_pending'):
                await admission.create(request,command)
            assert not admitted
            enqueue.assert_not_awaited()
            if scenario in ('lost_org_grant_after_orders','changed_session_after_orders'):
                assert list(receipts.values())[0]['outcome']==commitments[0] and not releases
                actor.organization_grants=organization_grants
                actor.actor.session_id='test-current'
        created = await admission.create(request,command)
        actor.permissions[:]=['identity.listings.publish',engine.SUSPENDED_ACTIVITY]
        assert await admission.create(request,command)==created
        actor.permissions[:]=['identity.listings.publish']
        assert await admission.create(request,command)==created
        with pytest.raises(PublicError,match='idempotency_conflict'):
            await admission.create(request,command.model_copy(update={'opening_minor':410000}))
        if scenario.startswith('suspended'):
            assert created['status']=='denied' and created['code']=='marketplace_activity_suspended'
            assert not admitted and not commitments
            enqueue.assert_not_awaited()
            assert deps.bid_admission.await_count==int(scenario=='suspended_at_fence')
            return
        deps.bid_admission.assert_awaited_once()
        if scenario=='superseded':
            assert created['status']=='denied' and created['code']=='listing_changed'
            assert not admitted and len(commitments)==1 and len(releases)==2 and releases[0]==releases[1]
            enqueue.assert_not_awaited()
            return
        assert created['status']=='succeeded'
        if scenario in ('lost_response','lost_org_grant_after_orders','changed_session_after_orders'):
            assert len(commitments)==2 and commitments[0]==commitments[1]
        enqueue.assert_awaited_once()
        deps.json.assert_awaited_with('catalog','GET',f'/v1/listings/{listing}',request)
        actor.actor.subject_id=buyer
        actor.actor.organization_id=None
        actor.organizations=[]
        actor.roles=['buyer']
        page = await my_bids(request,Response(),view='calendar',limit=50,cursor=None)
        assert page['total']==1 and page['items'][0]['auction_id']==created['auction_id']
        assert page['items'][0]['is_demo'] is is_demo

    asyncio.run(run())
