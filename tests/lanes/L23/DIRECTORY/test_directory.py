"""Deterministic route checks with local authority and storage contracts."""
import importlib.util
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.principal import CurrentPrincipal

ROOT = Path(__file__).resolve().parents[4]
BUSINESS, OTHER, ACTOR, OPTION = (UUID(int=i) for i in range(1, 5))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path / '__init__.py', submodule_search_locations=[str(ROOT / path)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader = None
    module.__path__ = [str(ROOT / path)]
    return importlib.import_module(name + '.routes')


directory = load('directory_l23', 'services/service-operations/modules/directory')
movement = load('movement_l23', 'services/catalog/modules/options/movement')


def principal(organization=BUSINESS, permissions=None):
    return CurrentPrincipal.model_validate({'actor': {'subject_id': str(ACTOR), 'session_id': str(ACTOR), 'organization_id': str(organization)},
        'roles': ['buyer'], 'organizations': [str(organization)], 'organization_grants': [
            {'organization_id': str(organization), 'permissions': permissions or ['business.jobs.write', 'business.stock.write']}]})


def profile(**changes):
    return directory.Profile(expected_revision=0, capabilities=['maintenance'], contact='Synthetic contact',
        visit_en='Visit by confirmed arrangement', visit_ar='الزيارة بترتيب مؤكد', scope_en='Declared maintenance', scope_ar='صيانة معلنة', **changes)


def option(**changes):
    value = dict(brand_id=BUSINESS, expected_revision=0, label_en='Synthetic movement', label_ar='حركة تجريبية',
        caliber='CAL-1', cases=['C-1'], dials=['D-1'], hands=['H-1'], functions=['hours'], quote_minor=25000, currency='USD')
    value.update(changes)
    return movement.Option(**value)


class Store:
    def __init__(self):
        self.commands, self.profiles, self.choices, self.options, self.selections, self.events = {}, {}, {}, {}, {}, []
        self.archive = {}

    async def fetchrow(self, sql, *args):
        if sql.startswith('SELECT result FROM movement_selections'):
            return self.selections.get(args)
        if 'SELECT result FROM' in sql and '_commands' in sql:
            row=self.commands.get(args)
            return {'result':row['result']} if row else None
        if 'SELECT digest,result' in sql:
            return self.commands.get(args)
        if sql.startswith('SELECT * FROM directory_profiles'):
            return self.profiles.get(args[0])
        if sql.startswith('SELECT * FROM directory_choices'):
            return self.choices.get(args[0])
        if sql.startswith('SELECT * FROM movement_options'):
            row = self.options.get(args[0])
            return row if row and (len(args) < 2 or row['brand_id'] == args[1]) and (row.get('active', True) or 'AND active' not in sql) else None
        if sql.startswith('SELECT * FROM movement_selections'):
            return self.selections.get(args)
        if sql.startswith('INSERT INTO directory_choices'):
            row = dict(zip(('actor_id', 'id', 'organization_id', 'capability', 'purpose', 'revision', 'profile_revision'), args))
            self.choices[args[0]] = row
            return row
        if sql.startswith('INSERT INTO movement_options'):
            row = dict(zip(('id','brand_id','revision','label_en','label_ar','caliber','cases','dials','hands','functions','quote_minor','currency','active','compatibility_rules'),args))
            self.options[args[0]] = row
            return row
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        if '_commands' in sql:
            self.commands[args[:3]] = {'digest': args[3], 'result': args[4]}
        elif sql.startswith('INSERT INTO directory_profiles'):
            self.profiles[args[0]] = dict(zip(('organization_id','revision','capabilities','contact','visit_en','visit_ar','scope_en','scope_ar','published'),args))
        elif sql.startswith('INSERT INTO movement_selection_archive'):
            self.archive.setdefault(args[:3], args[3])
        elif sql.startswith('INSERT INTO movement_selections'):
            self.selections[args[:2]] = {'id': args[2], 'revision': args[4], 'result':args[-1]}
        else:
            raise AssertionError(sql)

    async def fetch(self, sql, *args):
        if 'directory_profiles' in sql:
            after,purpose,limit=args
            rows=[row for identifier,row in sorted(self.profiles.items()) if row['published'] and (after is None or identifier>after) and ('customization' in row['capabilities'] if purpose=='customization' else any(item!='customization' for item in row['capabilities']))]
            return rows[:limit]
        brand,after,limit=args
        return [row for identifier,row in sorted(self.options.items()) if row['brand_id']==brand and (row['active'] or 'AND active' not in sql) and row['currency']=='USD' and (after is None or identifier>after)][:limit]

    async def fetchval(self, sql, *args):
        if 'directory_profiles' in sql:
            return sum(row['published'] and ('customization' in row['capabilities'] if args[0]=='customization' else any(item!='customization' for item in row['capabilities'])) for row in self.profiles.values())
        return sum(row['brand_id']==args[0] and row['active'] and row['currency']=='USD' for row in self.options.values())

    @asynccontextmanager
    async def acquire(self):
        yield self


@pytest.fixture
def context(monkeypatch):
    store = Store()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=store)), state=SimpleNamespace(request_id='synthetic-request'))
    authority = SimpleNamespace(actor=principal(), denied=False, unavailable=False, kind='brand')

    async def scoped(request, organization=None):
        return authority.actor

    async def official(request, organization, **kwargs):
        if authority.unavailable:
            raise PublicError('unavailable', 'Current business unavailable.', status=503)
        if authority.denied or (kwargs.get('brand_only') and authority.kind != 'brand'):
            raise PublicError('not_official', 'Current business denied.', status=409)
        return SimpleNamespace(public_name='Synthetic business',kind=authority.kind,sample=True,capabilities=['servicing','customization'])

    @asynccontextmanager
    async def transaction(pool, **kwargs):
        yield store

    async def enqueue(tx, event, destinations):
        tx.events.append(event)

    for module in (directory, movement):
        monkeypatch.setattr(module, 'scoped_principal', scoped)
        monkeypatch.setattr(module, 'official', official)
        monkeypatch.setattr(module, 'unit_of_work', transaction)
        monkeypatch.setattr(module, 'enqueue', enqueue)
    return store, request, authority


@pytest.mark.asyncio
async def test_offering_permission_business_revision_and_recovery(context):
    store, request, authority = context
    authority.actor = principal(OTHER)
    with pytest.raises(AccessDenied):
        await directory.publish(BUSINESS, profile(), request, 'profile-0001')
    assert not store.profiles and not store.events
    authority.actor = principal()
    first = await directory.publish(BUSINESS, profile(), request, 'profile-0001')
    assert first['revision'] == 1
    # Lost response: original reference returns the same result without another event.
    assert await directory.publish(BUSINESS, profile(), request, 'profile-0001') == first
    assert len(store.events) == 1
    with pytest.raises(PublicError, match='idempotency_conflict'):
        await directory.publish(BUSINESS, profile(published=False), request, 'profile-0001')
    with pytest.raises(PublicError, match='stale_revision'):
        await directory.publish(BUSINESS, profile(), request, 'profile-0002')
    authority.denied = True
    with pytest.raises(PublicError, match='not_official'):
        await directory.publish(BUSINESS, profile(), request, 'profile-0001')
    authority.denied = False
    authority.unavailable = True
    with pytest.raises(PublicError, match='unavailable'):
        await directory.publish(BUSINESS, profile(), request, 'profile-0001')
    authority.unavailable = False
    assert await directory.publish(BUSINESS, profile(), request, 'profile-0001') == first
    assert len(store.events) == 1


@pytest.mark.asyncio
async def test_choice_is_revision_bound_intent_and_unpublished_staff_read_is_private(context):
    store, request, authority = context
    await directory.publish(BUSINESS, profile(), request, 'profile-0001')
    body = directory.Choice(organization_id=BUSINESS, capability='maintenance',expected_revision=0,profile_revision=1)
    first = await directory.choose(body, request, authority.actor, 'choice-00001')
    assert first['revision'] == 1 and 'appointment' not in first and 'authorized' not in first
    assert await directory.choose(body, request, authority.actor, 'choice-00001') == first
    with pytest.raises(PublicError, match='stale_revision'):
        await directory.choose(body, request, authority.actor, 'choice-00002')
    store.profiles[BUSINESS]['revision'] = 2
    with pytest.raises(PublicError, match='stale_revision'):
        await directory.choose(body.model_copy(update={'expected_revision':1}), request, authority.actor, 'choice-00003')
    store.profiles[BUSINESS]['published'] = False
    assert (await directory.maintenance(BUSINESS, request))['profile']['published'] is False
    authority.actor = principal(OTHER)
    with pytest.raises(AccessDenied):
        await directory.maintenance(BUSINESS, request)


@pytest.mark.asyncio
async def test_movement_ownership_revision_replay_and_current_authority(context):
    store, request, authority = context
    first = await movement.publish(OPTION, option(), request, 'movement-0001')
    assert first['currency'] == 'USD'
    assert await movement.publish(OPTION, option(), request, 'movement-0001') == first
    assert len(store.events) == 1
    authority.actor = principal(OTHER)
    with pytest.raises(PublicError, match='forbidden'):
        await movement.publish(OPTION, option(brand_id=OTHER), request, 'movement-0002')
    authority.actor = principal()
    with pytest.raises(PublicError, match='stale_revision'):
        await movement.publish(OPTION, option(), request, 'movement-0002')
    authority.unavailable = True
    with pytest.raises(PublicError, match='unavailable'):
        await movement.publish(OPTION, option(), request, 'movement-0001')
    assert len(store.events) == 1


@pytest.mark.parametrize('value',[True,1.5,-1,1000000000000])
def test_money_rejects_noninteger_or_out_of_range(value):
    with pytest.raises(ValidationError):
        option(quote_minor=value)


def test_non_dollar_options_and_extra_authority_fields_are_refused():
    with pytest.raises(ValidationError):
        option(currency='EUR')
    with pytest.raises(ValidationError):
        option(work_authorized=True)


@pytest.mark.parametrize('state',['supported_for_review','incompatible','parts_unavailable'])
def test_exact_combination_is_required_and_never_grants_physical_pass(state):
    configuration = movement.Configuration(case='C-1',dial='D-1',hands='H-1',functions=['hours'])
    row = option().model_dump()
    assert movement.assess(row,configuration)['status'] == 'manual_review'
    row['compatibility_rules'] = [{**configuration.model_dump(),'state':state}]
    result = movement.assess(row,configuration)
    assert result['status'] == state and result['physical_feasibility_pass'] is False
    assert result['quote_impact'] == {'minor':25000,'currency':'USD','indicative':True}
    assert movement.assess(row,configuration.model_copy(update={'hands':'H-2'}))['status']=='manual_review'
    row['compatibility_rules'] *= 2
    assert movement.assess(row,configuration)['status']=='manual_review'


def test_identified_references_are_not_rewritten_between_languages():
    assert movement.Configuration(case='CASE-٤٠',dial='D',hands='H',functions=[]).case=='CASE-٤٠'


def test_published_request_schemas_match_runtime_models():
    for folder,models in [('packages/contracts-service/directory',{'profile':directory.Profile,'choice':directory.Choice}),('packages/contracts-catalog/options/movement',{'offering':movement.Option,'selection':movement.Selection})]:
        for name,model in models.items():
            assert json.loads((ROOT/folder/f'{name}.schema.v1.json').read_text())==model.model_json_schema()


@pytest.mark.asyncio
@pytest.mark.parametrize('count',[0,1,1000])
async def test_directory_cursor_reaches_every_published_profile_with_server_total(context,count):
    store,request,_=context
    for index in range(count):
        identifier=UUID(int=index+1)
        store.profiles[identifier]={'organization_id':identifier,'revision':1,**profile().model_dump(exclude={'expected_revision'})}
    seen=[]
    cursor=None
    while True:
        page=await directory.businesses(request,purpose='servicing',limit=20,after=cursor)
        assert page['total']==count
        assert len(page['items'])<=20
        seen.extend(row['organization_id'] for row in page['items'])
        if page['next_after'] is None:break
        cursor=UUID(page['next_after'])
    assert len(seen)==len(set(seen))==count


@pytest.mark.asyncio
async def test_movement_selection_stale_denied_duplicate_lookup_and_recovery(context):
    store,request,authority=context
    await movement.publish(OPTION,option(),request,'movement-0001')
    body=movement.Selection(brand_id=BUSINESS,option_id=OPTION,expected_revision=0,option_revision=1,configuration={'case':'C-1','dial':'D-1','hands':'H-1','functions':['hours']})
    first=await movement.select(body,request,authority.actor,'selection-0001')
    assert first['status']=='manual_review'
    assert await movement.select(body,request,authority.actor,'selection-0001')==first
    assert (await movement.operation('selection-0001','select',request,authority.actor))['result']==first
    assert (await movement.operation('selection-0002','select',request,authority.actor))['state']=='pending'
    with pytest.raises(PublicError,match='stale_revision'):
        await movement.select(body,request,authority.actor,'selection-0002')
    with pytest.raises(PublicError,match='idempotency_conflict'):
        await movement.select(body.model_copy(update={'expected_revision':1}),request,authority.actor,'selection-0001')
    authority.unavailable=True
    with pytest.raises(PublicError,match='unavailable'):
        await movement.select(body,request,authority.actor,'selection-0001')
    authority.unavailable=False
    assert await movement.select(body,request,authority.actor,'selection-0001')==first
    assert len(store.events)==2

@pytest.mark.asyncio
async def test_operation_receipts_recheck_scope_and_buyer_permission(context):
    store,request,authority=context
    await directory.publish(BUSINESS,profile(),request,'profile-0001')
    assert (await directory.operation('profile-0001','publish:'+str(BUSINESS),request,authority.actor))['state']=='saved'
    authority.actor=principal(OTHER)
    with pytest.raises(AccessDenied):
        await directory.operation('profile-0001','publish:'+str(BUSINESS),request,authority.actor)
    authority.actor=principal()
    authority.denied=True
    with pytest.raises(PublicError,match='not_official'):
        await directory.operation('profile-0001','publish:'+str(BUSINESS),request,authority.actor)
    authority.denied=False
    actor=authority.actor.model_copy(update={'roles':[]})
    with pytest.raises(PublicError,match='forbidden'):
        await directory.operation('unknown-0001','choose',request,actor)
    with pytest.raises(PublicError,match='buyer_required'):
        await directory.current_choice(request,actor)
    with pytest.raises(PublicError,match='buyer_required'):
        await movement.current_selection(request,BUSINESS,actor)


@pytest.mark.asyncio
async def test_withdrawn_movement_remains_editable_only_to_current_stock_staff(context):
    store,request,authority=context
    await movement.publish(OPTION,option(active=False),request,'movement-0001')
    page=await movement.offerings(BUSINESS,request,limit=20,after=None)
    assert page['items'][0]['active'] is False
    authority.actor=principal(OTHER)
    with pytest.raises(AccessDenied):
        await movement.offerings(BUSINESS,request,limit=20,after=None)
    authority.actor=principal()
    await movement.publish(OPTION,option(expected_revision=1,active=True),request,'movement-0002')
    assert store.options[OPTION]['active'] is True and store.options[OPTION]['revision']==2


@pytest.mark.asyncio
async def test_legacy_offering_cannot_be_rewritten_and_requires_separate_usd_id(context):
    store, request, _ = context
    await movement.publish(OPTION, option(), request, 'movement-0001')
    store.options[OPTION]['currency'] = 'LBP'
    original = dict(store.options[OPTION])
    with pytest.raises(PublicError, match='archived_currency'):
        await movement.publish(OPTION, option(expected_revision=1), request, 'movement-0002')
    assert store.options[OPTION] == original
    replacement = UUID(int=50)
    await movement.publish(replacement, option(), request, 'movement-0003')
    assert store.options[replacement]['currency'] == 'USD'
    assert store.options[OPTION] == original


@pytest.mark.asyncio
async def test_archived_selection_revision_supports_explicit_replacement_and_preserves_snapshot(context):
    store, request, authority = context
    await movement.publish(OPTION, option(), request, 'movement-0001')
    body = movement.Selection(brand_id=BUSINESS, option_id=OPTION, expected_revision=0, option_revision=1,
        configuration={'case':'C-1','dial':'D-1','hands':'H-1','functions':['hours']})
    await movement.select(body, request, authority.actor, 'selection-0001')
    old = json.loads(store.selections[(ACTOR, BUSINESS)]['result'])
    old['quote_impact']['currency'] = 'LBP'
    snapshot = json.dumps(old)
    store.selections[(ACTOR, BUSINESS)]['result'] = snapshot
    current = await movement.current_selection(request, BUSINESS, authority.actor)
    assert current == {'selection':None, 'archived':True, 'selection_revision':1}
    with pytest.raises(PublicError, match='stale_revision'):
        await movement.select(body, request, authority.actor, 'selection-0002')
    replacement = body.model_copy(update={'expected_revision':current['selection_revision']})
    result = await movement.select(replacement, request, authority.actor, 'selection-0003')
    assert result['revision'] == 2 and result['quote_impact']['currency'] == 'USD'
    assert store.archive[(ACTOR, BUSINESS, 1)] == snapshot
    assert await movement.select(replacement, request, authority.actor, 'selection-0003') == result
    assert len(store.archive) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('command', ['select', 'publish'])
async def test_operation_lookup_hides_historic_amount_without_rewriting_receipt(context, command):
    store, request, authority = context
    result = {'id': str(OPTION), 'brand_id': str(BUSINESS), 'revision': 3}
    if command == 'select':
        result['quote_impact'] = {'minor': 90000, 'currency': 'LBP', 'indicative': True}
    else:
        result.update(currency='LBP', quote_minor=90000)
        command = 'publish:' + str(OPTION)
    snapshot = json.dumps(result)
    store.commands[(ACTOR, command, 'historic-0001')] = {'result': snapshot}
    response = await movement.operation('historic-0001', command, request, authority.actor)
    assert response['archived'] is True and response['result'] is None
    assert response['revision'] == 3 and response['operation_id'] == 'historic-0001'
    assert 'LBP' not in json.dumps(response)
    assert store.commands[(ACTOR, command, 'historic-0001')]['result'] == snapshot


@pytest.mark.asyncio
async def test_historic_selection_replay_excludes_archived_amount_and_preserves_receipt(context):
    store, request, authority = context
    await movement.publish(OPTION, option(), request, 'movement-0001')
    body = movement.Selection(brand_id=BUSINESS, option_id=OPTION, expected_revision=0, option_revision=1,
        configuration={'case':'C-1','dial':'D-1','hands':'H-1','functions':['hours']})
    await movement.select(body, request, authority.actor, 'selection-0001')
    key = (ACTOR, 'select', 'selection-0001')
    historic = json.loads(store.commands[key]['result'])
    historic['quote_impact']['currency'] = 'LBP'
    snapshot = json.dumps(historic)
    store.commands[key]['result'] = snapshot
    event_count = len(store.events)
    for _ in range(2):
        with pytest.raises(PublicError, match='archived_currency'):
            await movement.select(body, request, authority.actor, 'selection-0001')
        assert store.commands[key]['result'] == snapshot
        assert len(store.events) == event_count
