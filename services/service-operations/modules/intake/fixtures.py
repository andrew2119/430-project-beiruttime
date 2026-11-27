"""Opt-in preparatory sample; no received watch or technical pass is invented."""
import os
from uuid import UUID
from bt_bulkheads import DependencyClient, Unavailable


async def seed(settings):
    order=UUID(os.environ['BT_SAMPLE_ORDER_ID'])
    organization=UUID(os.environ['BT_SAMPLE_ORGANIZATION_ID'])
    token=os.environ['BT_SAMPLE_TECHNICAL_TOKEN']
    client=DependencyClient('service-operations',os.getenv('BT_SERVICE_OPERATIONS_URL','http://service-operations:8000'),timeout=2,concurrency=1)
    try:
        response=await client.request('POST',f'/v1/intake/records?organization_id={organization}',headers={
            'Authorization':'Bearer '+token,'Idempotency-Key':'sample-intake-'+order.hex},json={
            'order_id':str(order),'custody_receipt_id':None,'serial':'SAMPLE — awaiting physical intake',
            'reference':'SAMPLE — not verified','movement':'SAMPLE — not assessed',
            'received_condition':'SAMPLE CONTENT — preparatory record; watch not received.',
            'accessories':'Not received','reported_issue':'SAMPLE — requested assessment',
            'assessed_issue':'','diagnostic_opening_permission':False,
            'no_polish_acknowledged':False,'fee_acknowledged':False,'fee_minor':0,'currency':'USD'})
        if isinstance(response,Unavailable) or response.status_code not in (200,201):
            raise RuntimeError('Sample preparatory intake was not confirmed by Service Operations')
    finally:
        await client.aclose()
