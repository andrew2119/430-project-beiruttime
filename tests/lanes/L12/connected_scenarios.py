"""Real HTTP/browser scenarios used only by connected.py's isolated stack."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4
import httpx

PASSWORD='Sample-only-L12-passphrase!'


class Scenarios:
    def __init__(self,origin,out,project):
        self.origin,self.out,self.project=origin,out,project
        self.client=httpx.Client(base_url=origin,headers={'Origin':origin},timeout=30)
        self.accounts={}
        self.evidence=[]
        self.auctions={}

    def call(self,service,method,path,actor=None,body=None,expected=(200,201),headers=None,*,direct_auction=False):
        h={'Idempotency-Key':str(uuid4()),**(headers or {})}
        if actor:h['Authorization']='Bearer '+self.accounts[actor]['access_token']
        if direct_auction:
            assert service=='auction'
        target='http://127.0.0.1:3413'+path if direct_auction else '/api/web/v1/'+service+path
        response=self.client.request(method,target,json=body,headers=h)
        self.evidence.append({'service':service,'method':method,'path':path.split('?')[0],'status':response.status_code})
        assert response.status_code in expected,(service,path,response.status_code,response.text[:1000])
        return response.json()

    def login(self,name):
        self.accounts[name]=self.call('identity','POST','/v1/accounts/login',body={'email':name+'.l12@example.test','password':PASSWORD})
        return self.accounts[name]

    def prepare(self):
        for name in ['operator','seller','dealer','buyer-a','buyer-b']:
            self.call('identity','POST','/v1/accounts/register',body={'email':name+'.l12@example.test','password':PASSWORD,'display_name':'Sample L12 '+name})
            self.login(name)
        result=subprocess.run(['docker','exec',self.project+'-identity','python','-m','service_app.bootstrap_operator',
            '--email','operator.l12@example.test','--reason','Synthetic isolated L12 acceptance operator'],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        operator=self.login('operator')
        application=self.call('identity','POST','/v1/private-seller/applications','seller',{
            'identity_name':'DEMO Sample L12 Seller','contact':'seller.l12@example.test','payout_reference':'DEMO-L12-SELLER',
            'identity_evidence':'DEMO: synthetic identity only','possession_evidence':'DEMO: illustrative sample stock','expected_revision':0})['application']
        review=self.call('identity','POST','/v1/private-reviews','operator',{'application_id':application['id'],
            'reviewer_id':operator['account']['id'],'reason':'Review explicitly synthetic sample seller'})
        self.call('identity','POST','/v1/private-reviews/'+review['id']+'/verdict','operator',{
            'revision':review['revision'],'application_revision':application['revision'],'state':'approved',
            'reason':'Synthetic evidence approved, not physical watch authentication'})
        self.login('seller')
        business=self.call('identity','POST','/v1/businesses','operator',{'legal_name':'Sample L12 Dealer','public_name':'Sample L12 Dealer',
            'kind':'dealer','capabilities':['sales','servicing'],'assurance_reference':'SAMPLE-L12','reason':'Explicit sample stock import','sample':True})
        self.call('identity','POST','/v1/memberships','operator',{'business_id':business['id'],'subject_id':self.accounts['dealer']['account']['id'],
            'capabilities':['business.stock.write','business.jobs.write','business.records.read','business.staff.manage'],
            'qualifications':['Sample course dealer'],'intervention_scope':'Synthetic records only','reason':'Authorize sample importer'})
        self.login('dealer')
        values={'BT_ENVIRONMENT':'demo','BT_DEMO_IMPORT_ACK':'illustrative-stock-only',
            'BT_DEMO_PRIVATE_TOKEN':self.accounts['seller']['access_token'],'BT_DEMO_DEALER_TOKEN':self.accounts['dealer']['access_token'],
            'BT_DEMO_DEALER_ORGANIZATION_ID':business['id']}
        args=['docker','exec']
        for key in values:args+=['-e',key]
        result=subprocess.run([*args,self.project+'-catalog','python','-m','bt_runtime.fixtures','L03.listings','demo'],
            env={**os.environ,**values},capture_output=True,text=True)
        assert result.returncode==0,result.stderr[-3000:]
        listings=self.call('catalog','GET','/v1/seller/listings','seller')['items']
        self.listings={row['facts']['reference']:row for row in listings if row['is_demo']}
        assert len(self.listings)==3 and all(row['status']=='published' for row in self.listings.values())
        print('Real Identity onboarding and guarded Catalog sample publication passed.',flush=True)

    def create(self,reference,seconds=3600):
        listing=self.listings[reference]
        now=datetime.now(timezone.utc)
        rules={'currency':'USD','opening_minor':400000,'reserve_minor':450000,'increment_bands':[{'from_minor':0,'step_minor':10000}],
               'starts_at':(now-timedelta(seconds=1)).isoformat(),'ends_at':(now+timedelta(seconds=seconds)).isoformat()}
        result=self.call('auction','POST','/v1/auctions','seller',{'listing_id':listing['id'],**rules})
        assert result['status']=='succeeded',result
        id=result.get('auction_id') or result['auction']['id']
        self.auctions[reference]=id
        return id

    def policy_cases(self):
        id=self.create('DEMO-WATCH-01')
        path=f'/v2/auctions/{id}/policy'
        policy=self.call('auction','GET',path)
        seller_path=f'/v2/seller/auctions/{id}/policy'
        private=self.call('auction','GET',seller_path,'seller')
        assert policy['policy_version']=='fixed-end.v2' and policy['reserve_set'] and not policy['frozen']
        assert private['reserve_met'] is False and private['cancellation_eligible'] is True
        assert {'reserve_minor','reserve_met','maximum','buy_now_minor'}.isdisjoint(policy)
        self.call('auction','GET',seller_path,'buyer-a',expected=(403,))
        # The gateway exposes reads only; exercise the retained writer at the service boundary.
        writer=f'/v1/auctions/{id}/policy'
        body={'extension_policy':'last-two-minutes.v1','buy_now_minor':500000}
        self.call('auction','PATCH',writer,'buyer-a',body,expected=(403,),direct_auction=True)
        denied=self.call('auction','PATCH',writer,'seller',body,expected=(409,),direct_auction=True)
        assert denied['error']['code']=='fixed_end_policy',denied
        after=self.call('auction','GET',path)
        assert (after['revision'],after['end_version'],after['current_ends_at'])==(policy['revision'],policy['end_version'],policy['current_ends_at'])
        print('Real seller/public policy permissions, reserve privacy and fixed-end denial passed.',flush=True)

    def browser(self):
        env={**os.environ,'CHROME_DEVTOOLS_AXI_SESSION':'bt-s2-l12'}
        script=Path(__file__).with_name('connected-browser.js').read_text()
        context={'origin':self.origin,'password':PASSWORD,'listing':self.listings['DEMO-WATCH-01']['id']}
        def cli(*args,stdin=None):
            result=subprocess.run(['chrome-devtools-axi',*args],input=stdin,capture_output=True,text=True,env=env)
            assert result.returncode==0,result.stdout+result.stderr
            return result.stdout
        cli('open',self.origin+'/en/account')
        try:
            for width in [1280,390]:
                cli('emulate','--viewport',str(width)+'x844x3'+(',mobile,touch' if width==390 else ''))
                result=cli('run',stdin='const CONTEXT='+json.dumps({**context,'width':width})+';\n'+script)
                (self.out/f'browser-{width}.json').write_text(result)
        finally:cli('stop')
        id=self.auctions['DEMO-WATCH-01']
        history=self.call('auction','GET',f'/v1/auctions/{id}/history')['items']
        assert len(history)==1 and history[0]['sequence']==1 and history[0]['amount_minor']==400000,history
        for actor in ('buyer-a','buyer-b'):
            assert self.call('auction','GET',f'/v2/auctions/{id}/my-prebid',actor)['operation'] is None
        # Separate real login lineage for headless screenshots; never reuse a rotated refresh cookie.
        response=self.client.post('/api/web/v1/identity/v1/accounts/login',json={'email':'buyer-a.l12@example.test','password':PASSWORD})
        assert response.status_code==200
        import asyncio
        from connected_shots import screenshots
        asyncio.run(screenshots(self.origin,self.out,self.listings['DEMO-WATCH-01']['id'],response.cookies.get('bt_refresh')))
        self.evidence.append({'browser_bid_minor':history[0]['amount_minor'],'accepted_bid_count':len(history),'lost_response_recovered':True})
        print('Authenticated browser policy, exact bid review and lost-response recovery passed.',flush=True)

    def quote(self,actor,id,amount):
        lot=self.call('auction','GET','/v1/auctions/'+id)
        body={'subject_id':id,'subject_revision':lot['revision'],'purpose':'bid','source':'sample','schedule_id':'usd-v2','currency':'USD','price_minor':amount}
        quote=self.call('pricing','POST','/v1/quotes',actor,body)
        quote=self.call('pricing','POST','/v1/quotes/'+quote['id']+'/review',actor,{**body,'quote_revision':quote['revision'],'payable_minor':quote['payable_minor']})
        return lot,quote

    def bid(self,actor,id,kind,amount):
        lot,quote=self.quote(actor,id,amount)
        result=self.call('auction','POST',f'/v1/auctions/{id}/{kind}',actor,{'amount_minor':amount,'fee_quote_id':quote['id'],'expected_revision':lot['revision']})
        assert result['status']=='succeeded',result
        return self.call('auction','GET','/v1/auctions/'+id)

    def race(self):
        id=self.create('DEMO-WATCH-03')
        lot,bid_quote=self.quote('buyer-b',id,600000)
        quote_denied=self.call('pricing','POST','/v1/auction-quotes','buyer-a',{'auction_id':id,'expected_revision':lot['revision']},expected=(409,))
        assert quote_denied['error']['code']=='auction_purchase_disabled',quote_denied
        path=f'/v1/auctions/{id}/prebid-buy-now'
        old_command={'quote_id':str(uuid4()),'expected_revision':lot['revision']}
        key={'Idempotency-Key':str(uuid4())}
        def command(kind):
            if kind=='bid':return kind,self.call('auction','POST',f'/v1/auctions/{id}/maximum','buyer-b',{'amount_minor':600000,'fee_quote_id':bid_quote['id'],'expected_revision':lot['revision']})
            return kind,self.call('auction','POST',path,'buyer-a',old_command,expected=(409,),headers=key,direct_auction=True)
        with ThreadPoolExecutor(max_workers=2) as pool:results=dict(pool.map(command,['bid','prebid']))
        assert results['bid']['status']=='succeeded' and results['prebid']['error']['code']=='auction_purchase_removed',results
        retry=self.call('auction','POST',path,'buyer-a',old_command,expected=(409,),headers=key,direct_auction=True)
        assert retry['error']['code']=='auction_purchase_removed',retry
        current=self.call('auction','GET',f'/v2/auctions/{id}')
        assert current['mode']=='bidding' and current['accepted_sequence']==1,current
        for actor in ('buyer-a','buyer-b'):
            assert self.call('auction','GET',f'/v2/auctions/{id}/my-prebid',actor)['operation'] is None
            orders=self.call('orders','GET','/v1/orders',actor)['items']
            assert not any(order['listing_id']==lot['listing_id'] for order in orders),orders
        self.evidence.append({'race':{'mode':current['mode'],'accepted_sequence':1,'purchase_denied':True}})
        print('Real first bid succeeded while current and legacy purchase requests were denied.',flush=True)

    def fixed_deadline_close(self):
        id=self.create('DEMO-WATCH-05',seconds=132)
        path=f'/v2/seller/auctions/{id}/policy'
        initial=self.call('auction','GET',path,'seller')
        first=self.bid('buyer-a',id,'maximum',600000)
        policy=self.call('auction','GET',path,'seller')
        assert first['current_minor']==400000 and not policy['reserve_met'] and policy['end_version']==initial['end_version']
        end=datetime.fromisoformat(policy['current_ends_at'])
        while (end-datetime.now(timezone.utc)).total_seconds()>118:time.sleep(.25)
        before=self.call('auction','GET','/v1/auctions/'+id)
        second=self.bid('buyer-b',id,'bids',410000)
        policy=self.call('auction','GET',path,'seller')
        assert second['accepted_sequence']==before['accepted_sequence']+2 and second['current_minor']==420000,(before,second)
        assert policy['end_version']==initial['end_version'] and datetime.fromisoformat(policy['current_ends_at'])==end
        assert not policy['reserve_met'] and policy['frozen'] and not policy['cancellation_eligible']
        denied=self.call('auction','PATCH',f'/v1/auctions/{id}/policy','seller',{'extension_policy':'last-two-minutes.v1','buy_now_minor':500000},expected=(409,),direct_auction=True)
        assert denied['error']['code']=='fixed_end_policy',denied
        history=self.call('auction','GET',f'/v1/auctions/{id}/history')
        assert '600000' not in json.dumps(history) and 'maximum_minor' not in json.dumps(history)
        print('Real late manual/proxy command left the fixed deadline unchanged; waiting for authoritative no-sale close.',flush=True)
        until=end+timedelta(seconds=15)
        result={}
        while datetime.now(timezone.utc)<until:
            # Closing result belongs to Auction's published API; direct port avoids registering L13's web routes in L12.
            response=httpx.get(f'http://127.0.0.1:3413/v1/auctions/{id}/result')
            result=response.json()
            if result.get('status')=='no_sale':break
            time.sleep(1)
        assert (result.get('status')=='no_sale' and result.get('order_available') is False
            and result.get('winner') is None and result.get('reason')=='reserve_not_met'
            and result.get('closing_minor')==420000 and result.get('end_version')==policy['end_version']
            and datetime.now(timezone.utc)>=datetime.fromisoformat(policy['current_ends_at'])),result
        self.evidence.append({'late_bid_fixed_end':policy,'closed_below_reserve':result})

    def save(self):
        (self.out/'evidence.json').write_text(json.dumps({'scope':'Real composed Identity/Catalog/Auction/Pricing/Orders and web; synthetic labeled sample content; no payment charged.',
            'checks':self.evidence},indent=2))
        self.client.close()
