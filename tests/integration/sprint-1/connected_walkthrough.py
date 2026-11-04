"""Fresh, explicitly synthetic course walkthrough against real composed services.

Run accounts, bootstrap the registered operator with Identity's local CLI, then
run onboard and publication. No SQL grants, request stubs or fabricated outcomes.
Local session evidence is ignored and mode 0600; public evidence omits credentials.
"""
import argparse
import base64
import time
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / 'artifacts/accept'
PASSWORD = 'Course-demo-passphrase!'
ACCOUNTS = ['operator', 'seller', 'dealer', 'brand', 'colleague', 'buyer-a', 'buyer-b']


class Walkthrough:
    def __init__(self, origin):
        self.origin = origin.rstrip('/')
        self.client = httpx.Client(base_url=self.origin, headers={'Origin':self.origin}, timeout=30)
        self.path = STATE / 'walkthrough.local.json'
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.evidence = []

    def save(self):
        STATE.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=2))

    def call(self, service, method, route, actor=None, body=None, *, headers=None, expected=(200,201), content=None):
        h = {'Idempotency-Key':str(uuid4()), **(headers or {})}
        if actor:
            h['Authorization'] = 'Bearer ' + self.state['accounts'][actor]['access_token']
        response = self.client.request(method, f'/api/web/v1/{service}'+route, json=body, content=content, headers=h)
        self.evidence.append({'service':service,'method':method,'route':route.split('?')[0],'status':response.status_code,'request_id':response.headers.get('x-request-id')})
        assert response.status_code in expected, (service,method,route,response.status_code,response.text[:600])
        return response.json()

    def login(self, name):
        existing=self.state.get('accounts',{}).get(name)
        if existing:
            payload=existing['access_token'].split('.')[1]
            expiry=json.loads(base64.urlsafe_b64decode(payload+'='*((-len(payload))%4)))['exp']
            # Client-side expiry is only a refresh hint; every service still
            # verifies the signature and fresh current Identity authority.
            if expiry > time.time()+30:
                return existing
            if existing.get('refresh_cookie'):
                self.client.cookies.clear()
                self.client.cookies.set('bt_refresh',existing['refresh_cookie'])
                result=self.call('identity','POST','/v1/accounts/refresh')
                result['refresh_cookie']=self.client.cookies.get('bt_refresh')
                self.state['accounts'][name]=result
                self.save()
                return result
        result = self.call('identity','POST','/v1/accounts/login',body={'email':name+'.s1@example.test','password':PASSWORD})
        result['refresh_cookie']=self.client.cookies.get('bt_refresh')
        self.state.setdefault('accounts',{})[name] = result
        self.save()
        return result

    def accounts(self):
        for name in ACCOUNTS:
            if name not in self.state.get('accounts',{}):
                result = self.call('identity','POST','/v1/accounts/register',body={'email':name+'.s1@example.test','password':PASSWORD,'display_name':'Sample '+name.title()}, expected=(201,409))
                if 'account' in result:
                    self.state.setdefault('accounts',{})[name] = result
                    self.save()
            self.login(name)

    def onboard(self):
        operator = self.login('operator')
        assert 'identity.businesses.manage' in operator['principal']['permissions'], 'Run Identity first-operator CLI first'
        self.state.setdefault('businesses',{})
        for kind in ['dealer','brand']:
            self.login(kind)
            if kind not in self.state['businesses']:
                business = self.call('identity','POST','/v1/businesses','operator',{
                    'legal_name':'Sample '+kind.title()+' Demonstration','public_name':'Sample '+kind.title(),
                    'kind':kind,'capabilities':['sales','servicing']+(['customization'] if kind=='brand' else []),
                    'assurance_reference':'SAMPLE-COURSE-ONBOARDING','reason':'Synthetic course business explicitly onboarded','sample':True})
                self.state['businesses'][kind]=business
                self.save()
                for name in [kind]+(['colleague'] if kind=='dealer' else []):
                    self.call('identity','POST','/v1/memberships','operator',{
                        'business_id':business['id'],'subject_id':self.state['accounts'][name]['account']['id'],
                        'capabilities':['business.stock.write','business.jobs.write','business.records.read','business.staff.manage'],
                        'qualifications':['Sample authorized course colleague'],'intervention_scope':'Synthetic demonstration records only',
                        'reason':'Authorize sample business colleague for course demonstration'})
            self.login(kind)
        self.login('seller')
        if 'application' not in self.state:
            application=self.call('identity','POST','/v1/private-seller/applications','seller',{
                'identity_name':'DEMO Sample Seller','contact':'seller.s1@example.test','payout_reference':'DEMO-SELLER-S1',
                'identity_evidence':'DEMO: synthetic identity reference only','possession_evidence':'DEMO: illustrative sample watch possession','expected_revision':0})['application']
            self.state['application']=application
            self.save()
        if 'review' not in self.state:
            application=self.state['application']
            review=self.call('identity','POST','/v1/private-reviews','operator',{
                'application_id':application['id'],'reviewer_id':operator['account']['id'],'reason':'Review synthetic course private seller evidence'})
            self.state['review']=review
            self.save()
        if 'verdict' not in self.state:
            self.state['verdict']=self.call('identity','POST','/v1/private-reviews/'+self.state['review']['id']+'/verdict','operator',{
                'revision':self.state['review']['revision'],'application_revision':self.state['application']['revision'],
                'state':'approved','reason':'Synthetic identity and possession reviewed; not physical watch authentication'})
            self.save()
        self.login('seller')
        print('Official sample dealer/brand, scoped colleagues and reviewed private seller ready.')

    def contacts(self):
        for name in ['seller','dealer','brand','buyer-a','buyer-b']:
            self.login(name)
            contact=self.call('identity','GET','/v1/contacts',name)
            if contact['email_verified']:
                continue
            email=name+'.s1@example.test'
            proof=self.call('identity','POST','/v1/accounts/reauthenticate',name,{'password':PASSWORD,'purpose':'contact-change','binding':'email:'+email})
            challenge=self.call('identity','POST','/v1/contacts/challenges',name,{'channel':'email','recipient':email,'revision':contact['revision'],'proof':proof['proof']})
            code=self.call('identity','GET','/v1/contacts/challenges/'+challenge['id']+'/sample-code',name)
            verified=self.call('identity','POST','/v1/contacts/challenges/'+challenge['id']+'/verify',name,{'code':code['code']})
            assert verified['email_verified'] and verified['email_sample']
        print('Sample contact verification completed through password reauthentication and one-use codes.')

    def auctions(self):
        self.login('seller'); self.login('dealer')
        self.state.setdefault('auctions',{})
        for reference,name in [('DEMO-WATCH-01','seller'),('DEMO-WATCH-03','seller')]:
            if reference in self.state['auctions']:
                continue
            listing=next(row for row in self.state['listings'] if row['facts']['reference']==reference)
            org='?organization_id='+self.state['businesses']['dealer']['id'] if name=='dealer' else ''
            now=datetime.now(timezone.utc)
            result=self.call('auction','POST','/v1/auctions'+org,name,{
                'listing_id':listing['id'],'currency':'USD','opening_minor':10000,
                'increment_bands':[{'from_minor':0,'step_minor':1000}],
                'starts_at':(now+timedelta(seconds=3) if reference=='DEMO-WATCH-01' else now+timedelta(hours=1)).isoformat(),
                'ends_at':(now+timedelta(hours=2)).isoformat()})
            assert result['status']=='succeeded',result
            self.state['auctions'][reference]=result
            self.save()
        print('Real private open and scheduled auctions created with Orders sale fences.')

    def quote(self, name, subject, revision, amount, purpose='bid', source='sample'):
        body={'subject_id':subject,'subject_revision':revision,'purpose':purpose,'source':source,'schedule_id':'sample-v1','currency':'USD','price_minor':amount}
        quote=self.call('pricing','POST','/v1/quotes',name,body)
        reviewed=self.call('pricing','POST','/v1/quotes/'+quote['id']+'/review',name,{**body,'quote_revision':quote['revision'],'payable_minor':quote['payable_minor']})
        assert reviewed['reviewed_at']
        return reviewed

    def bids(self):
        for name in ['buyer-a','buyer-b']:
            self.login(name)
        auction=self.state['auctions']['DEMO-WATCH-01']
        # No repeat after completion: use another fresh auction for a second run.
        auction_id=auction.get('auction_id') or auction.get('resource_id')
        if not auction_id:
            auction_id=auction['auction']['id']
        expected_prices=[10000,11000,12000,16000,20000,21000]
        steps=[('buyer-a','bids',10000),('buyer-b','bids',11000),('buyer-a','maximum',20000),('buyer-b','maximum',15000),('buyer-b','maximum',20000),('buyer-b','maximum',22000)]
        results=[]
        for (name,kind,amount),price in zip(steps,expected_prices):
            lot=self.call('auction','GET','/v1/auctions/'+auction_id)
            quote=self.quote(name,auction_id,lot['revision'],amount)
            result=self.call('auction','POST',f'/v1/auctions/{auction_id}/{kind}',name,{'amount_minor':amount,'fee_quote_id':quote['id'],'expected_revision':lot['revision']})
            assert result['status']=='succeeded',result
            current=self.call('auction','GET','/v1/auctions/'+auction_id)
            assert current['current_minor']==price,current
            results.append({'actor':name,'kind':kind,'current_minor':price,'revision':current['revision']})
        history=self.call('auction','GET',f'/v1/auctions/{auction_id}/history')
        assert 'maximum_minor' not in json.dumps(history) and 'maxima' not in json.dumps(history)
        self.state['bid_proof']={'auction_id':auction_id,'results':results,'history':history}
        self.save()
        print('Manual and private maximum bidding passed: 100,110,120,160,200,210 USD; earlier equal cap retained leadership.')

    def purchases(self):
        from concurrent.futures import ThreadPoolExecutor
        for name in ['buyer-a','buyer-b']:
            self.login(name)
        listing=next(row for row in self.state['listings'] if row['facts']['reference']=='DEMO-WATCH-02')
        quotes={name:self.quote(name,listing['id'],listing['revision'],listing['facts']['price_minor'],'purchase','listing') for name in ['buyer-a','buyer-b']}
        available=self.call('orders','GET','/v1/listings/'+listing['id']+'/availability')
        def reserve(name):
            return name,self.call('orders','POST','/v1/reservations',name,{'watch_id':listing['physical_watch_id'],'quote_id':quotes[name]['id'],'expected_revision':available['revision']})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(reserve,['buyer-a','buyer-b']))
        assert sorted(result['status'] for _,result in results)==['denied','succeeded'],results
        name,winner=next((name,result) for name,result in results if result['status']=='succeeded')
        assert winner['order']['quote_id']==quotes[name]['id'] and winner['order']['state']=='awaiting_payment'
        assert winner['order']['total_minor']==quotes[name]['payable_minor'] and winner['order']['payment_authority'] is False
        self.state['reservation']={'winner':name,**winner,'quote':quotes[name]}
        self.save()
        self.call('orders','GET','/v1/orders/'+winner['resource_id'],'buyer-b' if name=='buyer-a' else 'buyer-a',expected=(403,404))
        self.call('orders','POST','/v1/orders/'+winner['resource_id']+'/transitions',name,{'state':'paid','expected_revision':1,'reason':'Premature payment must be denied'},expected=(403,409,422))
        print('Two real buyers raced: exactly one awaiting-payment reservation, retained exact quote, other buyer denied.')

    def directory(self):
        self.state.setdefault('directory',{})
        for kind in ['dealer','brand']:
            self.login(kind)
            org=self.state['businesses'][kind]['id']
            if kind not in self.state['directory']:
                profile=self.call('service-operations','PUT','/v1/directory/businesses/'+org,kind,{
                    'expected_revision':0,'capabilities':['maintenance','repair']+(['customization'] if kind=='brand' else []),
                    'contact':kind+'.s1@example.test','visit_en':'Sample visit by arrangement; no appointment booked',
                    'visit_ar':'زيارة تجريبية بالتنسيق، لم يتم حجز موعد','scope_en':'Sample official business service profile; no work authorized',
                    'scope_ar':'ملف خدمة تجريبي لمنشأة رسمية، لا عمل مصرح به','published':True})
                self.state['directory'][kind]=profile;self.save()
        public=self.call('service-operations','GET','/v1/directory/businesses')
        assert len(public['items'])==2,public
        self.login('buyer-a')
        previous=self.call('service-operations','GET','/v1/directory/choices/current','buyer-a')
        choice=previous.get('choice')
        selected=self.call('service-operations','POST','/v1/directory/choices','buyer-a',{
            'organization_id':self.state['businesses']['dealer']['id'],'capability':'maintenance','purpose':'servicing',
            'expected_revision':choice['revision'] if choice else 0,'profile_revision':self.state['directory']['dealer']['revision']})
        self.state['service_choice']=selected;self.save()
        other=self.state['businesses']['brand']['id']
        self.call('service-operations','PUT','/v1/directory/businesses/'+other,'dealer',{
            'expected_revision':1,'capabilities':['maintenance'],'contact':'denied@example.test','visit_en':'Sample denial','visit_ar':'تجريبي',
            'scope_en':'Cross-business denial','scope_ar':'رفض وصول','published':True},expected=(403,))
        print('Real onboarded dealer and brand staff published scoped profiles; buyer chose servicing, cross-business write denied.')

    def request(self):
        self.login('buyer-a')
        if 'request_draft' not in self.state:
            result=self.call('catalog','POST','/v1/request-drafts','buyer-a',{'brand_id':self.state['businesses']['brand']['id'],
                'kind':'customization','watch_context':'owned_watch','watch_reference':'SAMPLE-COURSE-WATCH',
                'scope_intent':'Sample dial/color discussion, not approval','notes':'DEMO: private course request only','options':{}})
            assert result['status']=='succeeded',result
            self.state['request_draft']=result;self.save()
        result=self.state['request_draft']; print('DRAFT',json.dumps(result)[:1600])

    def publication(self):
        for name in ['seller','dealer']:
            self.login(name)
        # The owning Catalog importer uses the actual create/upload/fee/publish APIs.
        result = subprocess.run(['docker','compose','-f',str(STATE/'compose.local.json'),'exec','-T',
            '-e','BT_ENVIRONMENT=demo','-e','BT_DEMO_IMPORT_ACK=illustrative-stock-only',
            '-e','BT_DEMO_PRIVATE_TOKEN='+self.state['accounts']['seller']['access_token'],
            '-e','BT_DEMO_DEALER_TOKEN='+self.state['accounts']['dealer']['access_token'],
            '-e','BT_DEMO_DEALER_ORGANIZATION_ID='+self.state['businesses']['dealer']['id'],
            'catalog','python','-m','bt_runtime.fixtures','L03.listings','demo'],cwd=ROOT,capture_output=True,text=True)
        assert result.returncode==0, result.stderr[-2000:]
        print(result.stdout)
        listings=[]
        for name in ['seller','dealer']:
            org='?organization_id='+self.state['businesses']['dealer']['id'] if name=='dealer' else ''
            listings.extend(item for item in self.call('catalog','GET','/v1/seller/listings'+org,name)['items'] if item['is_demo'])
        self.state['listings']=listings
        assert len(listings)==6 and all(item['status']=='published' for item in listings)
        discovery=self.call('catalog','GET','/v1/discovery/watches')
        assert discovery['items'] and all(item['demo'] for item in discovery['items'])
        self.save()
        print('Six labeled sample listings published; auctions enter browse after scheduling.')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('phase', choices=['accounts','onboard','publication','contacts','auctions','bids','purchases','directory','request'])
    parser.add_argument('--origin',default='http://127.0.0.1:3300')
    args=parser.parse_args()
    walk=Walkthrough(args.origin)
    try:
        getattr(walk,args.phase)()
    finally:
        STATE.mkdir(parents=True,exist_ok=True)
        (STATE/(args.phase+'-evidence.json')).write_text(json.dumps(walk.evidence,indent=2))
        walk.client.close()


if __name__=='__main__':
    main()
