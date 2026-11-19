"""Contract-identical local provider and transaction double; no connected proof."""
import copy
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from bt_contracts.comms.saved_searches.models import Validation, Match

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


class Catalog:
    def __init__(self):
        self.answer = True
        self.public = True
        self.calls = []
        self.broken = False

    async def validate(self, criteria):
        if self.broken:
            raise TimeoutError()
        return Validation(criteria=criteria, semantics_revision='canonical-v1')

    async def match(self, publication, criteria, semantics_revision):
        self.calls.append((publication, criteria, semantics_revision))
        if self.broken:
            raise TimeoutError()
        return Match(**{key: getattr(publication, key) for key in ('occurrence_id', 'listing_id', 'watch_id', 'revision')},
                     semantics_revision=semantics_revision, matches=self.answer, currently_public=self.public)

    async def visible(self, listing_id, revision):
        return self.public


class Store:
    def __init__(self):
        self.searches = {}
        self.operations = {}
        self.deliveries = {}
        self.notices = {}
        self.now = NOW

    @asynccontextmanager
    async def transaction(self, **kwargs):
        before = copy.deepcopy(self.__dict__)
        try:
            yield self
        except BaseException:
            self.__dict__.update(before)
            raise

    async def fetchrow(self, sql, *args):
        if sql.startswith('SELECT'):
            owner, identifier = (args[0], args[1]) if 'l22_search_operations' in sql or 'l22_match_deliveries' in sql else (args[1], args[0])
            if 'l22_search_operations' in sql:
                return self.operations.get((owner, identifier))
            if 'l22_match_deliveries' in sql:
                return self.deliveries.get((owner, identifier))
            row = (self.notices if 'l22_match_notices' in sql else self.searches).get(identifier)
            return row if row and row['owner_id'] == owner and not ('NOT cleared' in sql and row['cleared']) else None
        if sql.startswith('INSERT INTO l22_saved_searches'):
            identifier, owner, name, criteria, semantics, enabled = args
            if identifier in self.searches:
                return None
            self.searches[identifier] = dict(id=identifier, owner_id=owner, name=name, criteria=criteria,
                semantics_revision=semantics, alerts_enabled=enabled, state='saved', revision=1,
                created_at=self.now, eligible_at=self.now)
            return self.searches[identifier].copy()
        if sql.startswith('UPDATE l22_saved_searches'):
            identifier, owner, name, criteria, semantics, enabled, state, reset = args
            row = self.searches[identifier]
            assert row['owner_id'] == owner
            row.update(name=name, criteria=criteria, semantics_revision=semantics, alerts_enabled=enabled, state=state, revision=row['revision'] + 1)
            if reset:
                row['eligible_at'] = self.now
            return row.copy()
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        if sql == 'SELECT clock_timestamp()':
            return self.now
        if 'count(*)' in sql:
            rows = self.notices.values() if 'l22_match_notices' in sql else self.searches.values()
            return sum(r['owner_id'] == args[0] and (not r['cleared'] if 'l22_match_notices' in sql else r['state'] == 'saved') for r in rows)
        raise AssertionError(sql)

    async def fetch(self, sql, *args):
        owner = args[0]
        if 'l22_match_notices' in sql:
            rows = [r.copy() for r in self.notices.values() if r['owner_id'] == owner and not r['cleared']]
        else:
            rows = [r.copy() for r in self.searches.values() if r['owner_id'] == owner and r['state'] == 'saved' and (r['alerts_enabled'] if 'AND alerts_enabled' in sql else True)]
        if len(args) == 3:
            return rows[args[1]:args[1] + args[2]]
        return rows[:101]

    async def execute(self, sql, *args):
        if sql == "SET LOCAL idle_in_transaction_session_timeout='8000'":
            return
        if sql.startswith('SELECT pg_advisory_xact_lock'):
            return
        if sql.startswith('INSERT INTO l22_search_operations'):
            owner, identifier, hashed, result = args
            self.operations[owner, identifier] = dict(request_hash=hashed, result=result)
        elif sql.startswith('INSERT INTO l22_match_deliveries'):
            owner, identifier, hashed = args
            self.deliveries[owner, identifier] = dict(request_hash=hashed)
        elif sql.startswith('INSERT INTO l22_match_notices'):
            identifier, owner, subscription, occurrence, listing, watch, revision, event_time, sample = args
            if not any(r['subscription_id'] == subscription and r['occurrence_id'] == occurrence for r in self.notices.values()):
                self.notices[identifier] = dict(id=identifier, owner_id=owner, subscription_id=subscription, occurrence_id=occurrence,
                    listing_id=listing, watch_id=watch, source_revision=revision, event_time=event_time, sample=sample, read=False, cleared=False, revision=1)
        elif sql.startswith('UPDATE l22_match_notices'):
            identifier, owner = args
            assert self.notices[identifier]['owner_id'] == owner
            field = 'cleared' if 'cleared=true' in sql else 'read'
            self.notices[identifier][field] = True
            self.notices[identifier]['revision'] += 1
        else:
            raise AssertionError(sql)


class Pool:
    def __init__(self, store):
        self.store = store

    @asynccontextmanager
    async def acquire(self, **kwargs):
        yield self.store
