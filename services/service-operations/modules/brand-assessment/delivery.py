"""One bounded delivery attempt; scheduling belongs to runtime composition."""
import asyncio
import json
from datetime import datetime, timedelta, timezone


async def deliver_one(store, catalog, now=None):
    now = now or datetime.now(timezone.utc)
    store.db.execute('BEGIN IMMEDIATE')
    try:
        row = store.db.execute('''SELECT operation,body,attempts FROM l17_outbox
            WHERE delivered=0 AND attempts<5 AND next_at<=? ORDER BY rowid LIMIT 1''', (now.isoformat(),)).fetchone()
        if not row:
            store.db.execute('COMMIT')
            return False
        operation, body, attempts = row
        command = json.loads(body)
        store.db.execute('''UPDATE l17_outbox SET attempts=attempts+1,next_at=?
            WHERE operation=? AND delivered=0 AND attempts=? AND attempts<5 AND next_at<=?''',
            ((now + timedelta(seconds=30 * (attempts + 1))).isoformat(), operation, attempts, now.isoformat()))
        if attempts == 4:
            result = json.loads(store.db.execute('SELECT body FROM l17_records WHERE subject=?', (command['subject_id'],)).fetchone()[0])
            result.update(next_actor=result.get('responsible_operator_id') or 'assignment_unavailable', pending_reason='catalog_unavailable')
            retained = json.dumps(result)
            store.db.execute('UPDATE l17_records SET body=? WHERE subject=?', (retained, command['subject_id']))
            store.db.execute('UPDATE l17_receipts SET body=? WHERE operation=?', (retained, operation))
        store.db.execute('COMMIT')
    except Exception:
        store.db.execute('ROLLBACK')
        raise
    try:
        receipt = await asyncio.wait_for(catalog.request_correction({
            'schema_version': 'catalog.request-correction.v1',
            'operation_id': operation, 'request_id': command['subject_id'],
            'request_revision': command['request_revision'], 'watch_id': command['watch_id'],
            'brand_id': command['organization_id'], 'assessor_id': command['actor_id'],
            'assignment_revision': command['assignment_revision'], 'reason': command['reason'],
        }), timeout=1.2)
        matching = (isinstance(receipt, dict) and receipt.get('state') == 'revised'
            and receipt.get('operation_id') == operation and receipt.get('brand_id') == command['organization_id']
            and receipt.get('watch_id') == command['watch_id'] and receipt.get('request_id') == command['subject_id']
            and type(receipt.get('previous_revision')) is int and receipt['previous_revision'] == command['request_revision']
            and type(receipt.get('request_revision')) is int and receipt['request_revision'] == command['request_revision'] + 1)
        if matching:
            store.catalog_receipt(operation, receipt['request_id'], receipt['previous_revision'], receipt['request_revision'])
            return True
    except (TimeoutError, ConnectionError, ValueError):
        pass
    return False
