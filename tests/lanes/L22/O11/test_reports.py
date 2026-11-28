import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[4]
MODULE = ROOT / 'services/orders/modules/financial-reports/model.py'
spec = importlib.util.spec_from_file_location('financial_reports', MODULE)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
Projection, Authority = module.Projection, module.Authority
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def event(sequence, kind, amount, **changes):
    return dict(sequence=sequence,event_id=f'event-{sequence}',order_id='order-1',watch_id='watch-1',seller_id='seller-1',organization_id=None,source_revision=sequence,quote_id='quote-1',quote_revision=1,policy_revision='policy-1',kind=kind,state='confirmed',amount_minor=amount,currency='USD',occurred_at='2026-11-17T11:59:00Z',postings=[{'account':'cash','minor':amount},{'account':kind,'minor':-amount}],**changes)


def feed(events):
    return dict(schema_version='orders.financial-feed.v1',events=events,high_watermark=max((e['sequence'] for e in events),default=0),checked_at='2026-11-17T12:00:00Z')


def request(**changes):
    return dict(dict(operation_id='operation-1',actor_id='seller-1',organization_id=None,subject_id='seller-1',expected_revision=1,page=1,page_size=50,order_id=None,view='seller',action='read'),**changes)


class ReportsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = str(Path(self.folder.name)/'reports.sqlite')
        self.projection = Projection(self.path)
        self.authority = Authority('seller-1', None, 'seller-1', 1, True, order_ids=frozenset({'order-1'}))
        self.source = feed([event(1,'gross',500000), event(2,'fee_collected',25000), event(3,'payout',475000)])

    def tearDown(self):
        self.projection.close()
        self.folder.cleanup()

    def auth(self, *args, **kwargs):
        self.assertEqual(kwargs['timeout'],2)
        return self.authority

    def provider(self, *args, **kwargs):
        self.assertEqual(kwargs,dict(limit=500,timeout=2))
        return self.source

    def read(self, body=None, now=NOW):
        return self.projection.read(body or request(),'seller-1',self.auth,self.provider,now)

    def test_actual_totals_duplicate_and_restart(self):
        first = self.read()
        self.assertEqual(first['totals'],dict(gross=500000,buyer_fee_collected=0,fee_collected=25000,fee_owed=0,refund=0,net=475000,payout=475000))
        self.assertEqual(self.read(),first)
        self.projection.close()
        self.projection=Projection(self.path)
        self.assertEqual(self.projection.operation('operation-1','seller-1',self.auth,self.provider,NOW),first)

    def test_wrong_actor_org_record_and_stale_hide_aggregates(self):
        for change in [dict(actor_id='other'),dict(organization_id='other'),dict(order_id='other'),dict(expected_revision=2),dict(view='operator')]:
            with self.subTest(change=change):
                answer=self.read(request(**change))
                self.assertIn(answer['state'],('denied','stale'))
                self.assertNotIn('totals',answer)
                self.assertNotIn('items',answer)

    def test_revoked_lookup_and_revocation_during_read(self):
        self.read()
        self.authority=Authority('seller-1',None,'seller-1',2,False)
        self.assertEqual(self.projection.operation('operation-1','seller-1',self.auth,self.provider,NOW)['state'],'denied')
        count=0
        def changing(*args,**kwargs):
            nonlocal count
            count+=1
            return Authority('seller-1',None,'seller-1',count,True,order_ids=frozenset({'order-1'}))
        self.assertEqual(self.projection.read(request(),'seller-1',changing,self.provider,NOW)['state'],'denied')

    def test_timeout_durable_retry_conflicting_reference(self):
        def timeout(*args,**kwargs): raise TimeoutError()
        self.assertEqual(self.projection.read(request(),'seller-1',self.auth,timeout,NOW)['state'],'unavailable')
        self.projection.close()
        self.projection=Projection(self.path)
        self.assertEqual(self.projection.operation('operation-1','seller-1',self.auth,self.provider,NOW)['state'],'ready')
        self.assertEqual(self.read(request(page=2))['state'],'denied')

    def test_fresh_before_equal_after(self):
        for seconds,state in [(59,'ready'),(60,'ready'),(61,'pending')]:
            self.assertEqual(self.read(now=NOW+timedelta(seconds=seconds))['state'],state)

    def test_invalid_batches_rollback_and_hide_totals(self):
        variants=[]
        bad=copy.deepcopy(self.source);bad['events'][1]['postings'][0]['minor']=1;variants.append(bad)
        bad=copy.deepcopy(self.source);bad['events'][0]['currency']='EUR';variants.append(bad)
        bad=copy.deepcopy(self.source);bad['events'][0]['amount_minor']=float('inf');variants.append(bad)
        bad=copy.deepcopy(self.source);bad['events'][0]['amount_minor']=True;variants.append(bad)
        bad=copy.deepcopy(self.source);bad['events'][0]['sequence']=2;variants.append(bad)
        bad=copy.deepcopy(self.source);bad['events'][0]['evidence_refs']=['private'];variants.append(bad)
        for source in variants:
            self.projection.close()
            self.projection=Projection(':memory:')
            self.source=source
            answer=self.read()
            self.assertEqual(answer['state'],'drift')
            self.assertNotIn('totals',answer)
            self.assertEqual(self.projection.checkpoint,0)

    def test_delayed_conflicting_duplicate_pending(self):
        self.source['high_watermark']=4
        self.assertEqual(self.read()['state'],'pending')
        self.projection.close()
        self.projection=Projection(self.path)
        self.source['high_watermark']=3
        self.assertEqual(self.read()['state'],'pending')
        self.source['events'].append(event(4,'fee_owed',0))
        self.source['high_watermark']=4
        self.assertEqual(self.read()['state'],'ready')
        self.source['events'][0]['quote_id']='different'
        self.assertEqual(self.read()['state'],'drift')

    def test_pending_resolution_and_receivable(self):
        pending=event(3,'refund',500000);pending['state']='pending'
        self.source=feed([event(1,'gross',500000),event(2,'fee_owed',25000),pending])
        self.assertEqual(self.read()['state'],'pending')
        self.source['events'].append(event(4,'refund',500000));self.source['high_watermark']=4
        answer=self.read()
        self.assertEqual(answer['totals']['refund'],500000)
        self.assertEqual(answer['totals']['fee_collected'],0)
        self.assertEqual(answer['totals']['fee_owed'],25000)
        self.assertEqual(answer['totals']['net'],0)

    def test_operator_trial_and_zero_gross(self):
        self.authority=Authority('seller-1',None,'seller-1',1,True,True,frozenset({'order-1'}))
        answer=self.read(request(view='operator'))
        self.assertEqual(sum(answer['trial_balance'].values()),0)
        self.assertEqual(answer['take_rate'],dict(numerator=25000,denominator=500000))

    def test_scope_filters_before_totals(self):
        self.authority=Authority('seller-1',None,'seller-1',1,True,order_ids=frozenset())
        answer=self.read()
        self.assertEqual(answer['total_count'],0)
        self.assertEqual(answer['totals']['gross'],0)

    def test_language_csv_formula_and_exact_cents(self):
        answer=self.read()
        for locale in ('en','ar'):
            content=module.export_csv(answer,locale).decode('utf-8-sig')
            self.assertIn('"5000.00"',content)
            self.assertIn('"250.00"',content)
            import csv
            rows=list(csv.reader(content.splitlines()))
            self.assertEqual(rows[1][-1], 'Simulated receipt' if locale == 'en' else 'إيصال محاكاة')
            self.assertEqual(len(rows[0]),len(rows[1]))
        answer['items'][0]['order_id']=' \t=1+1'
        self.assertIn("' \t=1+1",module.export_csv(answer,'en').decode())
        answer['total_count']=1001
        with self.assertRaises(ValueError): module.export_csv(answer,'en')

    def test_thousand_rows_real_pagination_and_export(self):
        events=[]
        for index in range(1000):
            row=event(index+1,'gross',100)
            row.update(order_id=f'order-{index:04}',watch_id=f'watch-{index:04}')
            events.append(row)
        self.authority=Authority('seller-1',None,'seller-1',1,True,order_ids=frozenset(e['order_id'] for e in events))
        for start in (0,500):
            self.projection.ingest(dict(feed(events[start:start+500]),high_watermark=1000),NOW)
        self.source=dict(feed([]),high_watermark=1000)
        answer=self.read()
        self.assertEqual(len(answer['items']),50)
        self.assertEqual(answer['total_count'],1000)
        self.assertEqual(answer['totals']['gross'],100000)
        exported=self.read(request(operation_id='export-1',action='export'))
        self.assertEqual(len(exported['items']),1000)
        self.assertEqual(len(module.export_csv(exported,'ar').decode().splitlines()),1001)

    def test_drift_survives_restart_and_empty_response(self):
        self.read()
        self.source['events'][0]['quote_id']='changed'
        self.assertEqual(self.read()['state'],'drift')
        self.projection.close()
        self.projection=Projection(self.path)
        self.source=dict(feed([]),high_watermark=3)
        self.assertEqual(self.read()['state'],'drift')

    def test_buyer_fees_never_reduce_seller_net(self):
        self.source=feed([event(1,'gross',500000),event(2,'fee_collected',25000),event(3,'buyer_fee_collected',15000)])
        self.authority=Authority('seller-1',None,'seller-1',1,True,True,frozenset({'order-1'}))
        answer=self.read(request(view='operator'))
        self.assertEqual(answer['totals']['net'],475000)
        self.assertEqual(answer['take_rate']['numerator'],40000)

    def test_route_adapter_export_and_headers(self):
        import types
        package=types.ModuleType('report_boundary')
        package.__path__=[str(MODULE.parent)]
        sys.modules['report_boundary']=package
        sys.modules['report_boundary.model']=module
        route_spec=importlib.util.spec_from_file_location('report_boundary.routes',MODULE.parent/'routes.py')
        routes=importlib.util.module_from_spec(route_spec)
        sys.modules[route_spec.name]=routes
        route_spec.loader.exec_module(routes)
        boundary=routes.Reports(self.projection,self.auth,self.provider)
        response=boundary.get('seller-1',request(action='export'),'ar',NOW)
        self.assertEqual(response.status,200)
        self.assertEqual(response.headers['Cache-Control'],'private, no-store')
        self.assertIn('text/csv',response.headers['Content-Type'])
        self.assertIn('الإجمالي',response.body.decode())
        response=boundary.get('other',request(),'en',NOW)
        self.assertEqual(response.status,403)
        self.assertNotIn('totals',response.body)
        self.source['events'][0]['quote_id']='changed'
        response=boundary.get('seller-1',request(operation_id='drift-read'),'en',NOW)
        self.assertEqual(response.status,200)
        self.assertEqual(response.body['state'],'drift')
        self.assertNotIn('totals',response.body)

    def test_contract_fixtures(self):
        fixture=json.loads((ROOT/'packages/contracts-orders/financial-reports/fixtures/current.v1.json').read_text())
        self.assertEqual(fixture['feed'],self.source)
        self.assertEqual(fixture['request'],request())
        self.assertEqual(self.read(),fixture['success'])


if __name__ == '__main__': unittest.main()
