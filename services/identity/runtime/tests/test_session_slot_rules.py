"""Pure rules for session slots, the one sample list and the sample-entry switch; no database or app."""
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
import pytest
from bt_contracts_core.errors import PublicError
from service_app import session_slots

try:
    from bt_runtime import demo_seed
except ImportError:  # a build without the deploy seed
    demo_seed = None

NOW = datetime(2026, 12, 1, 9, tzinfo=timezone.utc)
# The end of Tuesday 1 December 2026 in Beirut (UTC+2 in December), written out independently.
CUTOFF = datetime(2026, 12, 1, 22, tzinfo=timezone.utc)
STANDIN = 'operator-standin@example.test'
# The seed's own ids and addresses: uuid5 of its public demo keys, never a secret.
BUYER_ID, BUYER = session_slots.seed_account('demo', 'buyer')
STAFF_ID, STAFF = session_slots.seed_account('demo', 'staff')


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv('BT_DEMO_ENTRY_UNTIL', raising=False)
    monkeypatch.delenv('BT_DEMO_ENTRY_KEY_SHA256', raising=False)
    monkeypatch.delenv(session_slots.OPERATOR_SETTING, raising=False)


def request(headers):
    return SimpleNamespace(headers={key.lower(): value for key, value in headers.items()})


def document(*accounts, **override):
    return {'version': 1, 'about': 'test list', 'accounts': list(accounts)} | override


def entry(role='buyer', sample_set='demo', email=None, account_id=None):
    seed_id, seed_email = session_slots.seed_account(sample_set, role)
    return {'set': sample_set, 'role': role, 'email': email or seed_email, 'account_id': str(account_id or seed_id)}


@pytest.fixture
def listed(monkeypatch):
    accounts = session_slots.parse_sample_list(document(entry(), entry('staff'), entry('buyer', 'click-test')))
    monkeypatch.setattr(session_slots, 'sample_list', lambda: accounts)
    return accounts


def test_slot_header_is_optional_but_strict():
    assert session_slots.session_slot(request({})) is None
    slot = secrets.token_urlsafe(16)
    assert session_slots.session_slot(request({'X-BT-Session-Slot': slot})) == slot
    for bad in ('', 'a' * 21, 'a' * 23, 'a' * 21 + '=', 'a' * 21 + '.', 'a' * 21 + ';'):
        with pytest.raises(PublicError) as refused:
            session_slots.session_slot(request({'X-BT-Session-Slot': bad}))
        assert refused.value.code == 'invalid_session_slot' and refused.value.status == 400


def test_cookie_names_keep_the_ordinary_tab_unchanged():
    assert session_slots.refresh_cookie_name(None) == 'bt_refresh'
    assert session_slots.refresh_cookie_name('A' * 22) == 'bt_refresh_s_' + 'A' * 22


def test_the_shipped_list_names_every_listed_seed_account_of_both_sets_and_no_operator():
    # Read from the packaged contracts, exactly as the running service reads it.
    shipped = session_slots.sample_list()
    assert session_slots.ROLES == ('buyer', 'seller', 'staff', 'operator', 'rival')
    # The Operator link is bound by its own setting, so the list never names an operator.
    assert session_slots.LISTED_ROLES == ('buyer', 'seller', 'staff', 'rival')
    assert session_slots.OPERATOR_SETTING == 'BT_DEMO_OPERATOR_EMAIL'
    assert session_slots.SETS == ('demo', 'click-test')
    assert sorted((item.sample_set, item.role) for item in shipped) == sorted(
        (name, role) for name in session_slots.SETS for role in session_slots.LISTED_ROLES)
    assert all((item.account_id, item.email) == session_slots.seed_account(item.sample_set, item.role) for item in shipped)


def test_seed_ids_follow_the_seed_namespace_and_key_scheme():
    # Two values copied from the seed's accounts.json pin its namespace and key scheme.
    assert str(session_slots.SEED_NAMESPACE) == '51ba9d9c-94a2-5604-9c6d-6d0bf31b6409'
    assert session_slots.seed_account('demo', 'buyer') == (UUID('f45cd555-8b5c-5a27-905c-1fd480191ca6'), 'buyer.demo@example.test')
    assert session_slots.seed_account('click-test', 'staff') == (UUID('2b35cdec-1c4c-5196-a772-b7db3c3e7400'), 'staff.click-test@example.test')


def test_a_valid_list_keeps_set_role_address_and_seed_id():
    parsed = session_slots.parse_sample_list(document(entry(), entry('staff'), entry('buyer', 'click-test')))
    other_id, other = session_slots.seed_account('click-test', 'buyer')
    assert parsed == (session_slots.SampleAccount('demo', 'buyer', BUYER, BUYER_ID), session_slots.SampleAccount('demo', 'staff', STAFF, STAFF_ID),
                      session_slots.SampleAccount('click-test', 'buyer', other, other_id))
    assert session_slots.parse_sample_list(document()) == ()


@pytest.mark.parametrize('broken', [
    pytest.param(document(entry(account_id=uuid4())), id='registration-uuid4'),
    pytest.param(document(entry(account_id=uuid5(NAMESPACE_URL, 'test:' + secrets.token_hex(8)))), id='uuid5-not-from-the-seed'),
    pytest.param(document(entry(account_id=session_slots.seed_account('click-test', 'buyer')[0])), id='other-set-id'),
    pytest.param(document(entry(account_id=STAFF_ID)), id='other-role-id'),
    pytest.param(document(entry(email='other@example.test')), id='address-not-from-the-seed'),
    pytest.param(document(entry(email='buyer.click-test@example.test')), id='other-set-address'),
    pytest.param(document(entry() | {'account_id': str(BUYER_ID).upper()}), id='uppercase-id'),
    pytest.param(document(entry() | {'account_id': BUYER_ID.hex}), id='non-canonical-id'),
    pytest.param(document(entry() | {'account_id': 'not-an-id'}), id='not-a-uuid'),
    pytest.param(document(entry() | {'account_id': 5}), id='id-not-text'),
    pytest.param(document(entry(), entry()), id='role-twice-in-a-set'),
    pytest.param(document(entry(), entry('staff', email=BUYER)), id='address-twice'),
    pytest.param(document(entry(), entry('staff', account_id=BUYER_ID)), id='id-twice'),
    pytest.param(document(entry('brand')), id='unknown-role'),
    pytest.param(document(entry('operator')), id='operator-entry'),
    pytest.param(document(entry() | {'set': 'sunday'}), id='unknown-set'),
    pytest.param(document({key: value for key, value in entry().items() if key != 'set'}), id='no-set'),
    pytest.param(document(entry(email='buyer.demo@example.com')), id='not-example-test'),
    pytest.param(document(entry(email='Buyer.demo@example.test')), id='uppercase-address'),
    pytest.param(document(entry(email=' buyer.demo@example.test')), id='padded-address'),
    pytest.param(document(entry() | {'password': 'x'}), id='extra-entry-key'),
    pytest.param(document(entry(), version=2), id='version-2'),
    pytest.param(document(entry(), extra='x'), id='extra-list-key'),
    pytest.param(document(accounts={'buyer': entry()}), id='accounts-not-a-list'),
])
def test_any_broken_rule_refuses_the_whole_list(broken):
    with pytest.raises(ValueError):
        session_slots.parse_sample_list(broken)


def test_an_account_matches_only_by_both_seed_id_and_address(listed):
    assert session_slots.listed_role('demo', 'buyer').account_id == BUYER_ID
    assert session_slots.listed_role('click-test', 'buyer').account_id == session_slots.seed_account('click-test', 'buyer')[0]
    assert session_slots.listed_role('demo', 'operator') is None
    assert session_slots.listed_role('click-test', 'staff') is None
    assert session_slots.listed_account({'id': BUYER_ID, 'email': BUYER}).role == 'buyer'
    # Registration at a listed address makes a uuid4 id, so it never matches.
    assert session_slots.listed_account({'id': uuid4(), 'email': BUYER}) is None
    assert session_slots.listed_account({'id': BUYER_ID, 'email': STAFF}) is None


@pytest.mark.parametrize('until, on', [
    (NOW + timedelta(hours=3), True),
    (NOW + timedelta(hours=24), True),
    (NOW + timedelta(hours=24, seconds=1), False),
    (NOW, False),
    (NOW - timedelta(minutes=1), False),
])
def test_switch_needs_an_end_time_within_a_day(monkeypatch, until, on):
    monkeypatch.setenv('BT_DEMO_ENTRY_KEY_SHA256', hashlib.sha256(b'k' * 40).hexdigest())
    monkeypatch.setenv('BT_DEMO_ENTRY_UNTIL', until.isoformat())
    switch = session_slots.demo_switch(NOW)
    assert (switch is not None) is on
    assert switch is None or switch.until == until


@pytest.mark.parametrize('until, digest', [
    ('', 'a' * 64),
    ('2026-12-01T12:00:00+00:00', ''),
    ('2026-12-01T12:00:00', 'a' * 64),
    ('tomorrow', 'a' * 64),
    ('2026-12-01T12:00:00Z', 'a' * 63),
    ('2026-12-01T12:00:00Z', 'g' * 64),
])
def test_switch_is_off_unless_both_values_are_valid(monkeypatch, until, digest):
    monkeypatch.setenv('BT_DEMO_ENTRY_UNTIL', until)
    monkeypatch.setenv('BT_DEMO_ENTRY_KEY_SHA256', digest)
    assert session_slots.demo_switch(NOW) is None


@pytest.mark.parametrize('until', ['2026-12-01T12:00:00Z', '2026-12-01T14:00:00+02:00', '2026-12-01T07:00:00-05:00'])
def test_any_explicit_offset_names_the_same_end_time(monkeypatch, until):
    monkeypatch.setenv('BT_DEMO_ENTRY_UNTIL', until)
    monkeypatch.setenv('BT_DEMO_ENTRY_KEY_SHA256', 'A' * 64)
    switch = session_slots.demo_switch(NOW)
    assert switch.until == datetime(2026, 12, 1, 12, tzinfo=timezone.utc)
    monkeypatch.setenv('BT_DEMO_ENTRY_UNTIL', '2026-12-01T12:00:00+00:00')
    assert session_slots.demo_switch(NOW).activation == switch.activation


def test_each_key_and_end_time_is_its_own_activation_and_never_holds_the_key(monkeypatch):
    def activation(key, until):
        monkeypatch.setenv('BT_DEMO_ENTRY_KEY_SHA256', hashlib.sha256(key.encode()).hexdigest())
        monkeypatch.setenv('BT_DEMO_ENTRY_UNTIL', until.isoformat())
        return session_slots.demo_switch(NOW).activation
    key, other, until = secrets.token_urlsafe(32), secrets.token_urlsafe(32), NOW + timedelta(hours=2)
    first = activation(key, until)
    assert first == activation(key, until)
    assert first != activation(other, until)
    assert first != activation(key, until + timedelta(minutes=1))
    assert len(first) == 64 and key not in first and hashlib.sha256(key.encode()).hexdigest() not in first
    # The Operator setting is part of the activation: naming another account, or none, is new values.
    monkeypatch.setenv(session_slots.OPERATOR_SETTING, STANDIN)
    named = activation(key, until)
    assert named not in (first, activation(other, until)) and STANDIN not in named
    monkeypatch.setenv(session_slots.OPERATOR_SETTING, 'second-standin@example.test')
    assert activation(key, until) not in (first, named)
    # The same address however it is written is the same activation, and an unusable one counts as none.
    monkeypatch.setenv(session_slots.OPERATOR_SETTING, '  Operator-Standin@Example.TEST ')
    assert activation(key, until) == named
    monkeypatch.setenv(session_slots.OPERATOR_SETTING, 'not-an-address')
    assert activation(key, until) == first


def test_key_matches_only_its_digest(monkeypatch):
    key = secrets.token_urlsafe(32)
    assert not session_slots.demo_key_matches(key)
    monkeypatch.setenv('BT_DEMO_ENTRY_KEY_SHA256', hashlib.sha256(key.encode()).hexdigest())
    assert session_slots.demo_key_matches(key)
    assert not session_slots.demo_key_matches(key[:-1] + ('A' if key[-1] != 'A' else 'B'))
    short = 'k' * 31
    monkeypatch.setenv('BT_DEMO_ENTRY_KEY_SHA256', hashlib.sha256(short.encode()).hexdigest())
    assert not session_slots.demo_key_matches(short)


def test_a_link_session_holds_only_under_its_own_open_activation_and_listed_account(listed):
    current = session_slots.DemoSwitch(NOW + timedelta(hours=2), 'a' * 64)
    demo, account = {'role': 'buyer', 'activation': 'a' * 64}, {'id': BUYER_ID, 'email': BUYER}
    assert session_slots.link_session_holds(demo, current, False, account)
    assert not session_slots.link_session_holds(demo, None, False, account)
    assert not session_slots.link_session_holds(demo, current, True, account)
    assert not session_slots.link_session_holds(demo | {'activation': 'b' * 64}, current, False, account)
    assert not session_slots.link_session_holds(demo | {'role': 'staff'}, current, False, account)
    assert not session_slots.link_session_holds(demo | {'role': 'operator'}, current, False, account)
    assert not session_slots.link_session_holds(demo, current, False, account | {'id': uuid4()})
    assert not session_slots.link_session_holds(demo, current, False, account | {'email': STAFF})


@pytest.mark.parametrize('value, address', [
    (None, None), ('', None), ('   ', None), ('operator', None), ('two@at@example.test', None), ('nodot@localhost', None),
    ('has space@example.test', None), ('a' * 250 + '@example.test', None),
    ('operator-standin@example.test', 'operator-standin@example.test'),
    ('  Operator-Standin@Example.TEST \n', 'operator-standin@example.test'),
])
def test_the_operator_setting_names_one_address_or_nothing(monkeypatch, value, address):
    if value is not None:
        monkeypatch.setenv(session_slots.OPERATOR_SETTING, value)
    assert session_slots.operator_email() == address


def test_an_operator_link_session_holds_only_for_the_account_the_setting_names_now(listed, monkeypatch):
    current = session_slots.DemoSwitch(NOW + timedelta(hours=2), 'a' * 64)
    demo, account = {'role': 'operator', 'activation': 'a' * 64}, {'id': uuid4(), 'email': 'operator-standin@example.test'}

    def holds(demo, switch, closed, account):
        # Judged on Tuesday morning, before the Operator link's cutoff, whatever today's date is.
        return session_slots.link_session_holds(demo, switch, closed, account, now=NOW)
    assert not holds(demo, current, False, account)
    monkeypatch.setenv(session_slots.OPERATOR_SETTING, 'operator-standin@example.test')
    assert holds(demo, current, False, account)
    assert not holds(demo, None, False, account)
    assert not holds(demo, current, True, account)
    assert not holds(demo | {'activation': 'b' * 64}, current, False, account)
    assert not holds(demo | {'role': 'buyer'}, current, False, account)
    assert not holds(demo, current, False, account | {'email': 'other@example.test'})
    monkeypatch.setenv(session_slots.OPERATOR_SETTING, 'other@example.test')
    assert not holds(demo, current, False, account)
    # A listed sample account is never the Operator link's account, even when the setting names it.
    monkeypatch.setenv(session_slots.OPERATOR_SETTING, BUYER)
    assert not holds(demo, current, False, {'id': BUYER_ID, 'email': BUYER})
    monkeypatch.delenv(session_slots.OPERATOR_SETTING)
    assert not holds(demo, current, False, account)


@pytest.mark.parametrize('sample_set', session_slots.SETS)
@pytest.mark.parametrize('role', session_slots.ROLES)
def test_no_seed_account_is_ever_the_operator_links_account(monkeypatch, sample_set, role):
    """Ruling 261: every seed account, its two Operator accounts included, by its pinned id or its
    pinned address alone, whoever made the row and whatever grants it holds."""
    current = session_slots.DemoSwitch(NOW + timedelta(hours=2), 'a' * 64)
    demo = {'role': 'operator', 'activation': 'a' * 64}
    seed_id, seed_email = session_slots.seed_account(sample_set, role)
    for account, named in (({'id': seed_id, 'email': seed_email}, seed_email),
                           ({'id': uuid4(), 'email': seed_email}, seed_email),
                           ({'id': seed_id, 'email': STANDIN}, STANDIN)):
        assert session_slots.is_seed_account(account)
        monkeypatch.setenv(session_slots.OPERATOR_SETTING, named)
        assert not session_slots.link_session_holds(demo, current, False, account, now=NOW)
    monkeypatch.setenv(session_slots.OPERATOR_SETTING, STANDIN)
    assert not session_slots.is_seed_account({'id': uuid4(), 'email': STANDIN})
    assert session_slots.link_session_holds(demo, current, False, {'id': uuid4(), 'email': STANDIN}, now=NOW)


def test_the_seed_accounts_are_exactly_the_deploy_seeds_own():
    found = session_slots.seed_accounts()
    assert len(found) == len(set(found)) == len(session_slots.SETS) * len(session_slots.ROLES) == 10
    if getattr(demo_seed, 'accounts', None) is None:
        pytest.skip("needs the deploy seed's account list")
    assert sorted(found) == sorted((item.id, item.email) for item in demo_seed.accounts())
    if hasattr(demo_seed, 'SIGN_IN_ROLES'):
        assert set(demo_seed.SIGN_IN_ROLES) == set(session_slots.LISTED_ROLES)


def test_the_operator_link_cutoff_is_the_end_of_tuesday_1_december_in_beirut(listed, monkeypatch):
    """Ruling 252: fixed in code, so no setting can carry the Operator link past Tuesday; an
    earlier end time still ends it sooner, and the sample links keep their own end time."""
    assert session_slots.OPERATOR_LINK_CUTOFF == CUTOFF
    assert session_slots.operator_link_open(NOW) and session_slots.operator_link_open(CUTOFF - timedelta(microseconds=1))
    assert not session_slots.operator_link_open(CUTOFF) and not session_slots.operator_link_open(CUTOFF + timedelta(days=30))
    # The longest end time the switch accepts, set just before the cutoff, still stops the Operator link at it.
    monkeypatch.setenv('BT_DEMO_ENTRY_KEY_SHA256', hashlib.sha256(b'k' * 40).hexdigest())
    monkeypatch.setenv('BT_DEMO_ENTRY_UNTIL', (CUTOFF + timedelta(hours=20)).isoformat())
    late = session_slots.demo_switch(CUTOFF - timedelta(hours=1))
    assert late is not None
    assert session_slots.link_until('operator', late) == CUTOFF
    assert session_slots.link_until('buyer', late) == session_slots.link_until('staff', late) == late.until
    early = session_slots.DemoSwitch(NOW + timedelta(hours=2), 'b' * 64)
    assert session_slots.link_until('operator', early) == early.until == session_slots.link_until('buyer', early)
    # After the cutoff an open Operator link session stops holding; a sample link session does not.
    monkeypatch.setenv(session_slots.OPERATOR_SETTING, STANDIN)
    operator, account = {'role': 'operator', 'activation': late.activation}, {'id': uuid4(), 'email': STANDIN}
    assert session_slots.link_session_holds(operator, late, False, account, now=CUTOFF - timedelta(seconds=1))
    assert not session_slots.link_session_holds(operator, late, False, account, now=CUTOFF)
    buyer = {'role': 'buyer', 'activation': late.activation}
    assert session_slots.link_session_holds(buyer, late, False, {'id': BUYER_ID, 'email': BUYER}, now=CUTOFF)


def test_the_list_file_is_plain_json_with_no_secret_fields():
    from importlib.resources import files
    raw = json.loads(files('bt_contracts.identity.accounts').joinpath('sample-accounts.v1.json').read_text(encoding='utf-8'))
    assert set(raw) == {'version', 'about', 'accounts'}
    assert all(set(item) == {'set', 'role', 'email', 'account_id'} for item in raw['accounts'])
    assert all(isinstance(UUID(item['account_id']), UUID) for item in raw['accounts'])
