"""Synthetic public read-contract values, never a production demo importer."""
from datetime import datetime, timezone
from uuid import UUID


def reference(prefix,index=0):return str(UUID(f'{prefix}0000000-0000-4000-8000-{index+1:012d}'))
def listing_id(index=0):return reference('0',index)
def watch_id(index=0):return reference('1',index)
def asset_id(index=0,side=0):return reference('4',index*2+side)
def auction_id(index=0):return reference('5',index)


def source_row(index=0):
    identifier=listing_id(index)
    return {'id':identifier,'owner_subject_id':reference('2'),'organization_id':None,'seller_type':'private','seller_label':'Sample private seller','physical_watch_id':watch_id(index),'revision':3,'status':'published',
      'facts':{'brand':'Rolex','model':'Oyster Perpetual 36','reference':'124300','year':2020,'condition':'Contract fixture: seller-declared pre-owned condition.','component_wear':{'case':'Contract fixture: light case wear.'},'location':'Beirut','included':['box'],'no_documents':True,'modified':False,'modifications':[],'ownership_confirmed':True,'sale_mode':'auction','currency':'USD','price_minor':430000},
      'photo_ids':[asset_id(index,0),asset_id(index,1)],'cover_id':asset_id(index,0),'is_demo':True,
      'registration':{'watch_id':watch_id(index),'listing_id':identifier,'sale_mode':'auction','revision':1},
      'rules_version':'marketplace.s1.v1','published_at':datetime(2026,1,1,tzinfo=timezone.utc),'is_hidden':False}


def change_mode(row,mode):
    row['facts']['sale_mode']=mode
    row['registration']['sale_mode']={'fixed_price':'fixed','auction':'auction','offer':'seller_base'}[mode]


def credit():
    return {'title':'Contract geometry card','author':'Contract fixture','author_url':'','source_url':'','license':'Original synthetic test image','license_url':'','changes':'Not a watch photograph.','credit':'Original synthetic contract-test image.','alt_en':'Synthetic gallery contract card, not a watch photograph','alt_ar':'صورة اختبار اصطناعية وليست صورة ساعة','share_alike_required':False}
