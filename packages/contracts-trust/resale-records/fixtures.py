"""Synthetic development facts; never released transaction proof."""
from dataclasses import replace
from v1 import Command, Facts
COMMAND = Command('op-1','seller-1','org-1','recipient-1','watch-1','sale-1',0,3,2,1)
FACTS = Facts('seller-1','org-1','recipient-1','watch-1','sale-1',0,3,2,1,
              True,True,True,True,True,True,True,True,'a'*64,'Independent issuer',
              '2026-11-01T10:00:00Z','2026-11-16T10:00:00Z','Identity and condition',
              'public-watch-1',4,4,'2026-12-01T10:00:00Z')
FIXTURES = {'success': FACTS, 'denied': replace(FACTS,current_authority=False),
            'stale': replace(FACTS,source_revision=4), 'lost_response': FACTS}
