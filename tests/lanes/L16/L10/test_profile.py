import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('public_profile', ROOT / 'services/identity/modules/public-profile/profile.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.facts = json.loads((ROOT / 'packages/contracts-identity/public-profile/fixtures/source.v1.json').read_text())

    def read(self):
        return module.project('seller-1', 'read-1', self.facts)

    def test_private_fields_never_public(self):
        self.facts['identity'].update(contact='secret', proof='secret', logo='/media/logo.png', logo_approved=True)
        result = self.read()
        self.assertNotIn('secret', json.dumps(result))
        self.assertIsNone(result['identity']['logo'])
        self.facts['identity']['city_permitted'] = False
        self.assertIsNone(self.read()['identity']['city'])

    def test_duplicate_release_once_after_reconstruction(self):
        row = {'purchase_id':'p1','seller_id':'seller-1','state':'released','release_revision':1}
        self.facts['sales']['items'] = [row, copy.deepcopy(row)]
        self.facts['reviews']['items'] = [{'purchase_id':'p1','rating':5}]
        for _ in range(2):
            self.assertEqual(self.read()['sales']['released_count'], 1)
            self.assertEqual(self.read()['reviews']['distribution'], [0,0,0,0,1])

    def test_malformed_purchase_references_never_create_history(self):
        for reference in (None, '', ' ', 'p/1', 'p' * 81, 1, True, [], {}):
            with self.subTest(reference=reference):
                self.facts['sales']['items'] = [{'purchase_id': reference, 'seller_id': 'seller-1', 'state': 'released', 'release_revision': 1}]
                self.facts['reviews']['items'] = [{'purchase_id': reference, 'rating': 5}]
                result = self.read()
                self.assertEqual(result['sales'], {'state': 'unavailable', 'released_count': None})
                self.assertEqual(result['reviews'], {'state': 'unavailable', 'distribution': None})

    def test_malformed_review_reference_preserves_valid_sales(self):
        self.facts['sales']['items'] = [{'purchase_id': 'p1', 'seller_id': 'seller-1', 'state': 'released', 'release_revision': 1}]
        for reference in (None, '', ' ', 'p/1', 'p' * 81, 1, [], {}):
            with self.subTest(reference=reference):
                self.facts['reviews']['items'] = [{'purchase_id': reference, 'rating': 5}]
                result = self.read()
                self.assertEqual(result['sales']['released_count'], 1)
                self.assertEqual(result['reviews'], {'state': 'unavailable', 'distribution': None})

    def test_unavailable_reviews_not_zero(self):
        self.facts['reviews'] = {'state':'unavailable'}
        self.assertEqual(self.read()['reviews'], {'state':'unavailable','distribution':None})

    def test_section_failures_preserve_current_facts(self):
        for section in ('sales', 'reviews', 'listings'):
            for broken in (None, {}, *({'state': 'ready', 'subject_id': 'seller-1', 'identity_revision': 1, 'items': rows} for rows in (None, {}, ''))):
                with self.subTest(section=section, broken=broken):
                    facts = copy.deepcopy(self.facts)
                    facts[section] = broken
                    result = module.project('seller-1', 'read-1', facts)
                    self.assertEqual(result['state'], 'ready')
                    self.assertEqual(result['identity']['name'], facts['identity']['public_name'])
                    self.assertEqual(result[section]['state'], 'unavailable')
                    self.assertEqual(result['operation_id'], 'read-1')
                    if section != 'listings':
                        self.assertEqual(result['listings']['state'], 'ready')
            facts = copy.deepcopy(self.facts)
            del facts[section]
            result = module.project('seller-1', 'read-1', facts)
            self.assertEqual(result[section]['state'], 'unavailable')
            self.assertIsNotNone(result['identity'])
            if section == 'reviews':
                self.assertEqual(result['sales']['released_count'], 0)
                self.assertEqual(result['listings']['total'], 0)

    def test_no_history_no_rank(self):
        self.assertEqual(self.read()['sales']['released_count'], 0)
        self.assertEqual(self.read()['reviews']['distribution'], [0]*5)

    def test_denied_current_scope(self):
        self.facts['identity']['active'] = False
        self.assertIsNone(self.read()['identity'])
        self.assertEqual(self.read()['state'], 'denied')

    def test_stale_and_cross_seller(self):
        self.facts['sales']['identity_revision'] = 2
        self.assertEqual(self.read()['sales']['state'], 'stale')
        self.facts['listings']['subject_id'] = 'other'
        self.assertEqual(self.read()['listings']['state'], 'stale')

    def test_rating_boundaries(self):
        self.facts['sales']['items'] = [{'purchase_id':'p1','seller_id':'seller-1','state':'released','release_revision':1}]
        for rating in [0,1,5,6]:
            self.facts['reviews']['items'] = [{'purchase_id':'p1','rating':rating}]
            if rating in [1,5]:
                self.assertEqual(sum(self.read()['reviews']['distribution']), 1)
            else:
                self.assertEqual(self.read()['reviews']['state'], 'unavailable')

    def test_thousand_listing_pagination(self):
        for page in [1,50,51]:
            count = 20 if page <= 50 else 0
            self.facts['listings'].update(page=page,total=1000,items=[{'id':str(n),'title':'ساعات ⌚ long text','seller_id':'seller-1','state':'available_published'} for n in range(count)])
            result = module.project('seller-1','read-1',self.facts,page)
            self.assertEqual(result['listings']['total'],1000)
            self.assertEqual(len(result['listings']['items']),count)

    def test_timeout_and_lost_response(self):
        async def lost(subject,page): raise TimeoutError()
        result = asyncio.run(module.read_profile(lost,'seller-1','read-1'))
        self.assertEqual(result['state'],'unavailable')
        self.assertEqual(result['operation_id'],'read-1')

    def test_conflicting_duplicate(self):
        self.facts['sales']['items'] = [{'purchase_id':'p1','seller_id':'seller-1','state':state,'release_revision':1} for state in ['released','held']]
        self.assertEqual(self.read()['sales']['state'], 'unavailable')

    def test_permission_flags_fail_closed(self):
        for flag in ['active','public_permitted']:
            facts = copy.deepcopy(self.facts)
            facts['identity'][flag] = 'false'
            self.assertEqual(module.project('seller-1','read-1',facts)['state'],'denied')

    def test_dealer_assets_require_exact_approval(self):
        identity = self.facts['identity']
        identity.update(kind='dealer',organization_active=True,verification='dealer_business_verified',logo='/media/logo.png',logo_approved='false',banner='/media/banner.jpg',banner_approved=True)
        self.assertIsNone(self.read()['identity']['logo'])
        self.assertEqual(self.read()['identity']['banner'],'/media/banner.jpg')
        identity['logo_approved'] = True
        self.assertEqual(self.read()['identity']['logo'],'/media/logo.png')
        identity['logo'] = '/media/../private.png'
        self.assertIsNone(self.read()['identity']['logo'])
        identity['organization_active'] = False
        self.assertEqual(self.read()['state'],'denied')

    def test_route_status_and_no_store(self):
        import sys
        import types
        import httpx
        from fastapi import FastAPI
        package = types.ModuleType('public_profile_routes')
        package.__path__ = [str(ROOT / 'services/identity/modules/public-profile')]
        sys.modules[package.__name__] = package
        route_spec = importlib.util.spec_from_file_location('public_profile_routes.routes', ROOT / 'services/identity/modules/public-profile/routes.py')
        routes = importlib.util.module_from_spec(route_spec)
        route_spec.loader.exec_module(routes)

        async def run():
            for state, code in [('ready',200),('denied',403),('stale',409),('unavailable',503)]:
                async def provider(subject,page):
                    return self.facts if state == 'ready' else {'identity':{'state':state}}
                app = FastAPI()
                app.include_router(routes.create_router(provider))
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                    response = await client.get('/v1/public-profiles/seller-1?operation_id=read-1')
                    self.assertEqual(response.status_code,code)
                    self.assertEqual(response.headers['cache-control'],'no-store')
                    self.assertEqual(response.json()['subject_id'],'seller-1')
                    self.assertEqual(response.json()['operation_id'],'read-1')
                    retry = await client.get('/v1/public-profiles/seller-1?operation_id=read-1')
                    self.assertEqual(retry.json()['operation_id'], 'read-1')
                    self.assertEqual((await client.get('/v1/public-profiles/seller-1?operation_id=')).status_code, 422)
                    self.assertEqual((await client.get('/v1/public-profiles/seller-1?page=0')).status_code,422)
        asyncio.run(run())
