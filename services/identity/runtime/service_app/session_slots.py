"""Per-tab session slots and the switch-gated sample-account entry.

A slot is a random per-tab id that the web client keeps in sessionStorage and sends
as X-BT-Session-Slot. A slotted sign-in keeps its refresh handle in its own cookie,
bt_refresh_s_<slot>, so several tabs of one browser can hold different sample
accounts at once. A slot holds only a link session. A sample role's link session is for
an account on the one sample list, packages/contracts-identity/accounts/sample-accounts.v1.json,
matched by its fixed seed id and its address. Every listed id must be the deploy seed's own
uuid5 of its demo key for that set and role, so the list can name no other account, and
entry also needs the seed's own ownership record to hold that exact row (seed_owner_check).
The list names no operator: the Operator link opens the one existing account that
BT_DEMO_OPERATOR_EMAIL names, and only while that account is an active platform operator,
is none of the deploy seed's accounts (its two Operator accounts included) and the
Operator link's fixed cutoff has not passed (see modules/accounts/demo_entry.py). Only the
settings of the throwaway demo environment the kit runs in name that account, so the
repository holds no address of it. A typed sign-in or a registration never gets a slot; the
seed accounts have no usable password anyway. A request without the header keeps the
bt_refresh behaviour.

Sample-account entry signs a slot in without a typed password. It answers 404 unless
BT_DEMO_ENTRY_UNTIL holds an end time less than 24 hours ahead and
BT_DEMO_ENTRY_KEY_SHA256 holds the SHA-256 of the demo key. Those two values and the
Operator setting together are one activation. A link session belongs to the activation
that issued it and works only while that activation is the current one and has not been
closed; a closed activation never opens again (see modules/accounts/demo_entry.py).
"""
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import cache
from importlib.resources import files
from uuid import NAMESPACE_URL, UUID, uuid5
from bt_contracts_core.errors import PublicError

try:
    from bt_runtime import demo_seed
except ImportError:  # a build without the deploy seed: no sample role can enter (seed_owner_check)
    demo_seed = None

SLOT_HEADER = 'x-bt-session-slot'
SLOT_PATTERN = re.compile(r'[A-Za-z0-9_-]{22}')
DEMO_WINDOW = timedelta(hours=24)
ROLES = ('buyer', 'seller', 'staff', 'operator', 'rival')
# The roles the sample list may name; the Operator link is bound by OPERATOR_SETTING instead.
LISTED_ROLES = ('buyer', 'seller', 'staff', 'rival')
SETS = ('demo', 'click-test')
OPERATOR_SETTING = 'BT_DEMO_OPERATOR_EMAIL'
SAMPLE_EMAIL = re.compile(r'[a-z0-9._+-]+@example\.test')
# The deploy seed's namespace and key scheme (packages/runtime/src/bt_runtime/demo_seed.py
# once it lands): an account id is uuid5(SEED_NAMESPACE, 'DEMO-SEED-<SET>-ACCOUNT-<ROLE>').
SEED_NAMESPACE = uuid5(NAMESPACE_URL, 'urn:beirut-time:demo-seed:v1')
# The demo environment's Operator link is for Tuesday 1 December 2026 only (ruling 252). It
# ends at the end of that day in Beirut (UTC+2 in December), and no setting can move it later;
# an earlier BT_DEMO_ENTRY_UNTIL still ends it sooner. Only the Operator link has this cutoff.
OPERATOR_LINK_CUTOFF = datetime(2026, 12, 2, tzinfo=timezone(timedelta(hours=2)))


@dataclass(frozen=True)
class SampleAccount:
    sample_set: str
    role: str
    email: str
    account_id: UUID


@dataclass(frozen=True)
class DemoSwitch:
    until: datetime
    activation: str


def seed_account(sample_set: str, role: str) -> tuple[UUID, str]:
    """The id and address the deploy seed gives one set's account for one role."""
    return uuid5(SEED_NAMESPACE, f'DEMO-SEED-{sample_set}-ACCOUNT-{role}'.upper()), f'{role}.{sample_set}@example.test'


def seed_accounts() -> tuple[tuple[UUID, str], ...]:
    """The pinned id and address of every account the deploy seed makes, its two Operator accounts included."""
    return tuple(seed_account(sample_set, role) for sample_set in SETS for role in ROLES)


def is_seed_account(account) -> bool:
    """Whether an account row has any seed account's pinned id or pinned address.

    The Operator link never opens such a row, whoever created it and whatever grants it holds.
    """
    return any(account['id'] == account_id or account['email'] == email for account_id, email in seed_accounts())


def seed_owner_check():
    """The deploy seed's ownership check for one set's sample account, or None.

    bt_runtime.demo_seed.account_owner(tx, sample_set, role) (seed round 4) locks the row at the
    seed's pinned id and any row at its pinned address and answers 'owned' only when the row at
    the pinned id is the very row the seed inserted and entered in its ownership record
    (demo_seed_rows) under that account's demo key. None, in a build without that function,
    means no sample role can enter.
    """
    return getattr(demo_seed, 'account_owner', None)


def parse_sample_list(document) -> tuple[SampleAccount, ...]:
    """The validated sample list; any rule broken refuses the whole list."""
    if not isinstance(document, dict) or set(document) != {'version', 'about', 'accounts'}:
        raise ValueError('The sample list needs exactly version, about and accounts.')
    if document['version'] != 1 or not isinstance(document['about'], str) or not isinstance(document['accounts'], list):
        raise ValueError('The sample list must be version 1 with a list of accounts.')
    entries, roles, emails, ids = [], set(), set(), set()
    for item in document['accounts']:
        if not isinstance(item, dict) or set(item) != {'set', 'role', 'email', 'account_id'}:
            raise ValueError('Each sample account needs exactly set, role, email and account_id.')
        name, role, email, raw = item['set'], item['role'], item['email'], item['account_id']
        if name not in SETS or role not in LISTED_ROLES or (name, role) in roles:
            raise ValueError('Each sample role must be a listed role, listed once per known set.')
        if not isinstance(email, str) or not SAMPLE_EMAIL.fullmatch(email) or email in emails:
            raise ValueError('Each sample address must be a lowercase @example.test address, listed once.')
        try:
            account_id = UUID(raw)
        except (AttributeError, TypeError, ValueError):
            raise ValueError('Each sample account id must be a uuid.') from None
        # Public registration makes uuid4 ids; seed ids are uuid5 of public demo keys.
        if str(account_id) != raw or account_id.version != 5 or account_id in ids:
            raise ValueError('Each sample account id must be a canonical seed uuid5, listed once.')
        if (account_id, email) != seed_account(name, role):
            raise ValueError("Each sample account must be the seed's own account for its set and role.")
        roles.add((name, role))
        emails.add(email)
        ids.add(account_id)
        entries.append(SampleAccount(name, role, email, account_id))
    return tuple(entries)


@cache
def sample_list() -> tuple[SampleAccount, ...]:
    source = files('bt_contracts.identity.accounts').joinpath('sample-accounts.v1.json').read_text(encoding='utf-8')
    return parse_sample_list(json.loads(source))


def listed_role(sample_set: str, role: str) -> SampleAccount | None:
    return next((entry for entry in sample_list() if (entry.sample_set, entry.role) == (sample_set, role)), None)


def listed_account(account) -> SampleAccount | None:
    """The entry an account row matches by both its seed id and its address, if any."""
    return next((entry for entry in sample_list() if (entry.account_id, entry.email) == (account['id'], account['email'])), None)


def session_slot(request) -> str | None:
    """The caller's slot, or None for an ordinary tab."""
    raw = request.headers.get(SLOT_HEADER)
    if raw is None:
        return None
    if not SLOT_PATTERN.fullmatch(raw):
        raise PublicError('invalid_session_slot', 'Open the sample tab again.', status=400)
    return raw


def refresh_cookie_name(slot: str | None) -> str:
    return 'bt_refresh' if slot is None else 'bt_refresh_s_' + slot


def slot_refusal():
    """A typed sign-in or a registration in a sample tab, refused before any account is read."""
    return PublicError('slot_unavailable', 'Sample tabs sign in only from their sample link. Use an ordinary tab instead.', status=403)


def demo_key_digest() -> str | None:
    value = os.environ.get('BT_DEMO_ENTRY_KEY_SHA256', '').strip().lower()
    return value if re.fullmatch(r'[0-9a-f]{64}', value) else None


def demo_values() -> DemoSwitch | None:
    """This process's switch values as an activation, inside its time window or not.

    None when either switch value is unset or malformed. It never changes while a process
    runs, so it names the values a process was started with.
    """
    digest = demo_key_digest()
    raw = os.environ.get('BT_DEMO_ENTRY_UNTIL', '').strip()
    if not raw or not digest:
        return None
    try:
        until = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if until.tzinfo is None:
        return None
    # One activation per key fingerprint, end time and Operator setting, so changing any one of
    # them, the Operator setting alone included, is a new activation that ends the old one. The
    # key itself never enters it, and the hash shows the address to no one without the digest.
    marker = '|'.join(('demo-entry-activation-v2', digest, until.astimezone(timezone.utc).isoformat(), operator_email() or ''))
    return DemoSwitch(until, hashlib.sha256(marker.encode()).hexdigest())


def demo_switch(now: datetime | None = None) -> DemoSwitch | None:
    """The current activation while the switch is on, otherwise None."""
    values = demo_values()
    now = now or datetime.now(timezone.utc)
    if values is None or not now < values.until <= now + DEMO_WINDOW:
        return None
    return values


def demo_key_matches(key: str) -> bool:
    expected = demo_key_digest()
    if not expected or not 32 <= len(key) <= 200:
        return False
    return hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(), expected)


def operator_email() -> str | None:
    """The address of the one existing account the Operator link opens, or None.

    None when the setting is unset, empty or not an address, so the Operator link refuses.
    It is compared lowercase and trimmed, as a typed sign-in compares its address.
    """
    value = os.environ.get(OPERATOR_SETTING, '').strip().lower()
    if len(value) > 254 or value.count('@') != 1 or '.' not in value.split('@')[1] or any(c.isspace() for c in value):
        return None
    return value


def operator_link_open(now: datetime | None = None) -> bool:
    """Whether the Operator link's fixed cutoff is still ahead; no setting changes it."""
    return (now or datetime.now(timezone.utc)) < OPERATOR_LINK_CUTOFF


def link_until(role: str, switch: DemoSwitch) -> datetime:
    """When a new link session of this role ends: the switch end time, and the Operator link's cutoff if that is sooner."""
    return min(switch.until, OPERATOR_LINK_CUTOFF) if role == 'operator' else switch.until


def link_session_holds(demo, switch: DemoSwitch | None, closed: bool, account, now: datetime | None = None) -> bool:
    """A link session works only under the current, unclosed activation, for the account its role is bound to.

    A sample role's account is its listed seed account. Its session row references that
    account row, which therefore cannot be deleted and recreated while the session exists,
    so the seed ownership checked at entry still holds. The Operator link's account is the
    one the operator setting names now, and only before the Operator link's cutoff; no seed
    account is ever that account.
    """
    if switch is None or closed or demo['activation'] != switch.activation:
        return False
    if demo['role'] == 'operator':
        return operator_link_open(now) and account['email'] == operator_email() and not is_seed_account(account)
    entry = listed_account(account)
    return entry is not None and entry.role == demo['role']
