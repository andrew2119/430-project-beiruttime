import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module
v1=load('v1','packages/contracts-trust/resale-records/v1.py')
fixtures=load('resale_fixtures','packages/contracts-trust/resale-records/fixtures.py')
module=load('resale_store','services/trust/modules/resale-records/store.py')
NOW=datetime(2026,11,17,tzinfo=timezone.utc)

class Provider:
    def __init__(self,facts): self.facts=facts
    @contextmanager
    def locked_facts(self,command,timeout_seconds):
        assert timeout_seconds==2
        yield self.facts

class Transfers(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path=str(Path(self.folder.name)/'records.db')
        self.provider=Provider(fixtures.FACTS)
        self.store=module.Store(self.path,self.provider,responsible_operator='operator-1')
        self.c=fixtures.COMMAND
    def run_command(self,**changes):
        self.provider.facts=replace(fixtures.FACTS,**changes)
        with self.store.connect() as db:
            count=db.execute('SELECT COUNT(*) FROM l24_requests').fetchone()[0]
        command=replace(self.c,operation_id=f'case-{count}')
        return self.store.transfer(command,NOW)['state']
    def test_transfer_restart_lost_response(self):
        first=self.store.transfer(self.c,NOW)
        self.assertEqual(first['state'],'transferred')
        restarted=module.Store(self.path,self.provider,responsible_operator='operator-1')
        self.assertEqual(restarted.transfer(self.c,NOW),first)
        with restarted.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM l24_history').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM l24_outbox').fetchone()[0],1)
    def test_authority_and_actual_facts(self):
        for field in ('current_authority','seller_owns_record','recipient_authorized','released','prior_signature_valid','independent_pass','actual_custody','commitment_matches'):
            with self.subTest(field=field): self.assertEqual(self.run_command(**{field:False}),'denied')
    def test_wrong_scope(self):
        for field in ('actor_id','organization_id','subject_id','watch_id','sale_id'):
            with self.subTest(field=field): self.assertEqual(self.run_command(**{field:'other'}),'denied')
    def test_stale(self):
        for field in ('revision','source_revision','quote_revision','policy_revision'):
            with self.subTest(field=field): self.assertEqual(self.run_command(**{field:9}),'stale')
    def test_duplicate_conflict(self):
        self.store.transfer(self.c,NOW)
        self.assertEqual(self.store.transfer(replace(self.c,operation_id='other'),NOW)['state'],'duplicate')
        self.assertEqual(self.store.transfer(replace(self.c,quote_revision=99),NOW)['state'],'conflict')
    def test_revoked_retry_and_lookup(self):
        self.store.transfer(self.c,NOW)
        self.provider.facts=replace(fixtures.FACTS,current_authority=False)
        self.assertEqual(self.store.transfer(self.c,NOW)['state'],'denied')
        access=v1.Access('seller-1','org-1','recipient-1','watch-1',True)
        self.assertIsNone(self.store.lookup('op-1',access))
        self.provider.facts=fixtures.FACTS
        self.assertEqual(self.store.lookup('op-1',access)['state'],'transferred')
        for change in ({'allowed':False},{'organization_id':'other'},{'actor_id':'other'},{'watch_id':'other'},{'subject_id':'other'}):
            self.assertIsNone(self.store.lookup('op-1',replace(access,**change)))
    def test_timeout_retry(self):
        self.store.provider=module.MissingProvider()
        pending=self.store.transfer(self.c,NOW)
        self.assertEqual(pending['state'],'pending')
        self.assertEqual(pending['operation_id'],self.c.operation_id)
        self.assertIsNotNone(pending['next_review_at'])
        later=module.Store(self.path,module.MissingProvider(),responsible_operator='operator-2')
        retried=later.transfer(self.c,NOW+timedelta(hours=25))
        self.assertEqual(retried['next_review_at'],pending['next_review_at'])
        self.assertEqual(retried['escalation_at'],pending['escalation_at'])
        self.assertEqual(retried['next_actor'],'operator-1')
        self.assertEqual(later.transfer(replace(self.c,source_revision=99),NOW)['state'],'conflict')
        self.store.provider=self.provider
        recovered=self.store.lookup(self.c.operation_id,v1.Access('seller-1','org-1','recipient-1','watch-1',True))
        self.assertEqual(recovered['state'],'pending')
        self.assertEqual(recovered['next_review_at'],pending['next_review_at'])
        self.assertEqual(self.store.transfer(self.c,NOW)['state'],'transferred')
    def test_inspection_boundaries_and_modified(self):
        for deadline,expected in [('2026-11-17T00:00:01Z','prior_independent_inspection'),('2026-11-17T00:00:00Z','historical'),('2026-11-16T23:59:59Z','historical')]:
            with self.subTest(deadline=deadline),tempfile.TemporaryDirectory() as folder:
                store=module.Store(str(Path(folder)/'db'),Provider(replace(fixtures.FACTS,inspection_valid_until=deadline)),responsible_operator='operator-1')
                self.assertEqual(store.transfer(self.c,NOW)['state'],'transferred')
                with store.connect() as db:
                    summary=json.loads(db.execute('SELECT summary FROM l24_history').fetchone()[0])
                self.assertEqual(summary['qualification'],expected)
        self.assertEqual(self.run_command(current_watch_revision=5),'transferred')
        with self.store.connect() as db:
            summary=json.loads(db.execute('SELECT summary FROM l24_history').fetchone()[0])
        self.assertEqual(summary['qualification'],'historical')
        self.assertEqual(set(summary),{'issuer','inspected_at','scope','watch_reference','prior_hash','signed_record_hash','revision','qualification','hash'})
    def test_hash_chain(self):
        self.store.transfer(self.c,NOW)
        c=replace(self.c,operation_id='op-2',sale_id='sale-2',expected_revision=1)
        self.provider.facts=replace(fixtures.FACTS,sale_id='sale-2',revision=1,prior_hash='b'*64)
        self.assertEqual(self.store.transfer(c,NOW)['state'],'transferred')
        with self.store.connect() as db:
            rows=[json.loads(row[0]) for row in db.execute('SELECT summary FROM l24_history ORDER BY revision')]
        self.assertEqual(rows[1]['prior_hash'],rows[0]['hash'])
        self.assertEqual(rows[1]['signed_record_hash'],'b'*64)
        body={k:v for k,v in rows[1].items() if k!='hash'}
        self.assertEqual(rows[1]['hash'],module.hashlib.sha256(module.encoded(body).encode()).hexdigest())
    def test_terminal_failures_survive_restart_and_source_changes(self):
        access=v1.Access('seller-1','org-1','recipient-1','watch-1',True)
        for state, changes in (('denied', {'released':False}), ('stale', {'source_revision':9})):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as folder:
                path=str(Path(folder)/'db')
                provider=Provider(replace(fixtures.FACTS,**changes))
                store=module.Store(path,provider,responsible_operator='operator-1')
                first=store.transfer(self.c,NOW)
                self.assertEqual(first['state'],state)
                self.assertEqual(store.lookup(self.c.operation_id,access),first)
                provider.facts=fixtures.FACTS
                restarted=module.Store(path,provider,responsible_operator='operator-2')
                self.assertEqual(restarted.lookup(self.c.operation_id,access),first)
                self.assertEqual(restarted.transfer(self.c,NOW+timedelta(days=1)),first)
                self.assertEqual(restarted.transfer(replace(self.c,source_revision=8),NOW)['state'],'conflict')
                self.assertEqual(restarted.lookup(self.c.operation_id,access),first)
                provider.facts=replace(fixtures.FACTS,current_authority=False)
                self.assertIsNone(restarted.lookup(self.c.operation_id,access))
                provider.facts=fixtures.FACTS
                with restarted.connect() as db:
                    for table in ('l24_history','l24_transfers','l24_outbox'):
                        self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0],0)
                fresh=replace(self.c,operation_id='fresh')
                self.assertEqual(restarted.transfer(fresh,NOW)['state'],'transferred')

    def test_duplicate_receipt_survives_restart(self):
        self.store.transfer(self.c,NOW)
        duplicate=replace(self.c,operation_id='duplicate')
        first=self.store.transfer(duplicate,NOW)
        self.assertEqual(first['state'],'duplicate')
        restarted=module.Store(self.path,self.provider,responsible_operator='operator-1')
        access=v1.Access('seller-1','org-1','recipient-1','watch-1',True)
        self.assertEqual(restarted.lookup(duplicate.operation_id,access),first)
        self.assertEqual(restarted.transfer(duplicate,NOW),first)

    def test_bounds(self):
        for c in (replace(self.c,expected_revision=True),replace(self.c,operation_id='x'*129),replace(self.c,source_revision=-1)):
            with self.assertRaises(ValueError): self.store.transfer(c,NOW)
    def test_release_boundary(self):
        for released,expected in [('2026-11-17T00:00:01Z','denied'),('2026-11-17T00:00:00Z','transferred')]:
            with self.subTest(released=released): self.assertEqual(self.run_command(released_at=released),expected)

if __name__=='__main__': unittest.main()
