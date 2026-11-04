"""Strict, opt-in HTTP transport fixtures for the four public dependency contracts."""
import copy
from datetime import datetime, timedelta, timezone
from uuid import UUID
import httpx
from bt_bulkheads import DependencyClient
from fixture_data import auction_id, credit

class State:
    def __init__(self, rows, snapshot):
        self.rows={row['id']:row for row in rows}
        self.auctions={}
        self.histories={}
        self.orders_unavailable=False;self.auction_unavailable=False;self.identity_unavailable=False;self.credits_unavailable=False
        self.order_states={};self.revoked_businesses=set()
        for index,row in enumerate(rows):
            if row['facts']['sale_mode']!='auction':continue
            value=copy.deepcopy(snapshot)
            value.update(id=auction_id(index),listing_id=row['id'],current_minor=row['facts']['price_minor'] or 430000,next_minimum_minor=(row['facts']['price_minor'] or 430000)+10000,ends_at=(datetime.now(timezone.utc)+timedelta(hours=2,minutes=index)).isoformat())
            self.auctions[row['id']]=value
            self.histories[value['id']]=[{'sequence':1,'bidder':'Bidder A19F','amount_minor':value['current_minor'],'automatic':False,'received_at':'2026-11-04T04:59:59Z'}]

    def current(self, value):
        result=copy.deepcopy(value);result['server_time']=datetime.now(timezone.utc).isoformat();return result

    def timing(self, value, now):
        return {'auction_id':value['id'],'listing_id':value['listing_id'],'starts_at':value['starts_at'],'scheduled_ends_at':value['ends_at'],'current_ends_at':value['ends_at'],'server_time':now,'status':value['status'],'revision':value['revision'],'rules_version':value['rules_version'],'extension_policy':value['extension_policy']}

    def orders(self, request):
        if self.orders_unavailable:return httpx.Response(503)
        parts=request.url.path.split('/')
        if len(parts)!=5 or parts[1:3]!=['v1','listings']or parts[4]!='availability':return httpx.Response(404)
        row=self.rows.get(parts[3])
        if row is None:return httpx.Response(404)
        mode=row['registration']['sale_mode']
        state=self.order_states.get(row['id'],'fenced'if mode=='auction'and row['id']in self.auctions else'available')
        return httpx.Response(200,json={'watch_id':row['physical_watch_id'],'listing_id':row['id'],'sale_mode':mode,'status':state,'revision':9,'is_demo':row['is_demo']})

    def identity(self, request):
        if self.identity_unavailable:return httpx.Response(503)
        identifier=request.url.path.removeprefix('/v1/businesses/')
        row=next((row for row in self.rows.values()if row['organization_id']==identifier),None)
        if row is None:return httpx.Response(404)
        active=identifier not in self.revoked_businesses
        return httpx.Response(200,json={'id':identifier,'public_name':row['seller_label'],'kind':row['seller_type'],'capabilities':['sales'],'state':'active'if active else'revoked','revision':1,'sample':True,'platform_onboarded':active,'authenticated_business':active,'independent_watch_authentication_required':False})

    def media(self, request):
        if self.credits_unavailable:return httpx.Response(503)
        parts=request.url.path.split('/')
        row=self.rows.get(parts[3])if len(parts)==5 and parts[1:3]==['v1','listings']and parts[4]=='photo-credits'else None
        if row is None:return httpx.Response(404)
        return httpx.Response(200,json={'items':[{'asset_id':asset,'credit':credit()}for asset in row['photo_ids']]})

    def auction(self, request):
        if self.auction_unavailable:return httpx.Response(503)
        path=request.url.path
        if path=='/v1/auctions':
            identifier=request.url.params.get('listing_id')
            return httpx.Response(200,json={'items':[self.current(self.auctions[identifier])]if identifier in self.auctions else[]})
        if path=='/v1/auction-timing':
            now=datetime.now(timezone.utc).isoformat();params=request.url.params
            selected=params.get('listing_ids');requested=selected.split(',')if selected else None
            for identifier in requested or []:UUID(identifier)
            values=[self.timing(value,now)for key,value in self.auctions.items()if requested is None or key in requested]
            status=params.get('status','active')
            values=[value for value in values if status=='all'or(status=='active'and value['status']!='ended')or value['status']==status]
            values.sort(key=lambda value:(value['current_ends_at'],value['auction_id']))
            cursor=params.get('cursor')
            if cursor:
                position=next((i for i,value in enumerate(values)if value['auction_id']==cursor),None)
                if position is None:return httpx.Response(422)
                values=values[position+1:]
            limit=int(params.get('limit','100'));page=values[:limit]
            return httpx.Response(200,json={'version':1,'items':page,'server_time':now,'missing_listing_ids':[key for key in requested or []if key not in self.auctions],'next_cursor':page[-1]['auction_id']if len(values)>limit else None})
        if path.startswith('/v1/auctions/')and path.endswith('/history'):
            identifier=path.split('/')[3]
            value=next((value for value in self.auctions.values()if value['id']==identifier),None)
            if value is None:return httpx.Response(404)
            after=int(request.url.params.get('after_sequence','0'));limit=int(request.url.params.get('limit','50'))
            rows=[bid for bid in self.histories[identifier]if bid['sequence']>after]
            page=rows[:limit]
            return httpx.Response(200,json={'items':page,'has_more':len(rows)>limit,'next_sequence':page[-1]['sequence']if page else after,'snapshot':self.current(value)})
        return httpx.Response(404)

    def clients(self):
        return {name:DependencyClient(name,'http://'+name,timeout=.3,concurrency=16,transport=httpx.MockTransport(getattr(self,name)))for name in ('auction','orders','identity','media')}
