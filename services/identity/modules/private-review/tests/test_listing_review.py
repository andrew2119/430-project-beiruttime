"""Provider decisions against a transaction-local persistence stub."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from bt_runtime.modules import discover
from bt_contracts.catalog.listings.eligibility import PublicationEligibility

MODULES = Path(__file__).resolve().parents[2]


class Transaction:
    def __init__(self):
        self.rows = {}
        self.stock = []
        self.locks = []

    async def execute(self, sql, *args):
        import json
        if 'pg_advisory_xact_lock' in sql:
            self.locks.append(args[0])
        elif 'INSERT INTO l02_listing_reviews' in sql:
            row = self.rows.setdefault(args[0], {'proof': None})
            row['binding'] = json.loads(args[1])
        elif 'SET proof=NULL' in sql:
            self.rows[args[0]]['proof'] = None
            self.rows[args[0]]['stock_clearance'] = None
        elif 'INSERT INTO l02_listing_stock' in sql:
            self.stock.append(args)

    async def fetchrow(self, sql, listing):
        row = self.rows.get(listing)
        return dict(row) if row else None

    async def fetch(self, sql, digest, listing):
        return [{'listing_id': key} for identity, watch, key in self.stock if identity == digest and key != listing]

    async def fetchval(self, sql, *args):
        if len(args) == 2:
            watch, listing = args
            return next((key for _, identifier, key in self.stock if identifier == watch and key != listing), None)
        digest, watch, listing = args
        return next((key for identity, identifier, key in self.stock
                     if (identity == digest or identifier == watch) and key != listing), None)


@pytest.mark.asyncio
async def test_private_approval_duplicate_and_identity_change():
    from dataclasses import asdict
    import json
    module = next(m for m in discover(MODULES) if m.id == 'L02.private-review')
    provider = module.load('listing_review.py:ReviewProvider')()
    transitions = module.load('listing_review.py:possession')
    listing, actor, watch = uuid4(), uuid4(), uuid4()
    binding = dict(schema_version='listing-eligibility.v1', operation_id='test-review',
                   subject_id=str(listing), listing_id=str(listing), actor_id=str(actor), watch_id=str(watch),
                   organization_id=None, expected_revision=1, identity_digest='0' * 64)
    tx = Transaction()
    assert (await provider.validate(tx, binding))['state'] == 'pending'
    facts = module.load('listing_review.py:facts')(binding)
    now, challenge, reviewer = datetime.now(timezone.utc), uuid4(), uuid4()
    proof = transitions.issue(facts, actor, challenge, '123456', now)
    proof = transitions.submit(proof, facts, actor, 1, challenge, '123456', uuid4(), now, evidence_owned=True)
    proof = transitions.assign(proof, facts, 2, reviewer, operator_permitted=True, reviewer_qualified=True)
    proof = transitions.decide(proof, facts, reviewer, 3, 1, 'approved', 'Test photo inspected', reviewer_qualified=True)
    tx.rows[listing]['proof'] = json.dumps(asdict(proof), default=str)
    result = PublicationEligibility.model_validate(await provider.validate(tx, binding))
    assert result.state == 'eligible' and result.single_use_code_consumed
    assert len(set(tx.locks)) == 3
    duplicate = dict(binding, listing_id=str(uuid4()))
    duplicate['subject_id'] = duplicate['listing_id']
    assert (await provider.validate(tx, duplicate))['state'] == 'denied'
    assert (await provider.validate(tx, dict(binding, identity_digest='1' * 64)))['state'] == 'denied'
    assert tx.rows[UUID(binding['listing_id'])]['proof'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('organization', [uuid4(), uuid4()])
async def test_business_stock_admission_without_private_proof(organization):
    module = next(m for m in discover(MODULES) if m.id == 'L02.private-review')
    provider = module.load('listing_review.py:ReviewProvider')()
    listing = str(uuid4())
    binding = dict(schema_version='listing-eligibility.v1', operation_id='test-business-review',
                   subject_id=listing, listing_id=listing, actor_id=str(uuid4()), watch_id=str(uuid4()),
                   organization_id=str(organization), expected_revision=1, identity_digest='0' * 64)
    result = PublicationEligibility.model_validate(await provider.validate(Transaction(), binding))
    assert result.state == 'eligible' and result.duplicate_review == 'clear'


async def assert_revised_stock_retained(provider, tx, binding):
    assert (await provider.validate(tx, binding))['state'] == 'eligible'
    revised = dict(binding, identity_digest='1' * 64, watch_id=str(uuid4()))
    assert (await provider.validate(tx, revised))['state'] == 'denied'
    assert (await provider.validate(tx, revised))['state'] == 'eligible'
    for admitted in (binding, revised):
        duplicate = dict(admitted, listing_id=str(uuid4()))
        duplicate['subject_id'] = duplicate['listing_id']
        assert (await provider.validate(tx, duplicate))['state'] == 'denied'


@pytest.mark.asyncio
async def test_revised_business_stock_retains_every_admitted_identity():
    module = next(m for m in discover(MODULES) if m.id == 'L02.private-review')
    listing = str(uuid4())
    binding = dict(schema_version='listing-eligibility.v1', operation_id='test-revised-stock',
                   subject_id=listing, listing_id=listing, actor_id=str(uuid4()), watch_id=str(uuid4()),
                   organization_id=str(uuid4()), expected_revision=1, identity_digest='0' * 64)
    await assert_revised_stock_retained(module.load('listing_review.py:ReviewProvider')(), Transaction(), binding)


@pytest.mark.asyncio
async def test_matching_models_require_review_and_distinct_clearance():
    module = next(m for m in discover(MODULES) if m.id == 'L02.private-review')
    provider, tx = module.load('listing_review.py:ReviewProvider')(), Transaction()
    listing = str(uuid4())
    binding = dict(schema_version='listing-eligibility.v1', operation_id='test-stock-match',
                   subject_id=listing, listing_id=listing, actor_id=str(uuid4()), watch_id=str(uuid4()),
                   organization_id=str(uuid4()), expected_revision=1, identity_digest='0' * 64)
    assert (await provider.validate(tx, binding))['state'] == 'eligible'
    other = dict(binding, listing_id=str(uuid4()), watch_id=str(uuid4()))
    other['subject_id'] = other['listing_id']
    assert (await provider.validate(tx, other))['state'] == 'pending'
    tx.rows[UUID(other['listing_id'])]['stock_clearance'] = dict(matches=[listing], verdict='distinct')
    assert (await provider.validate(tx, other))['state'] == 'eligible'
    third = dict(binding, listing_id=str(uuid4()), watch_id=str(uuid4()))
    third['subject_id'] = third['listing_id']
    assert (await provider.validate(tx, third))['state'] == 'pending'
    tx.rows[UUID(third['listing_id'])]['stock_clearance'] = dict(matches=sorted([listing, other['listing_id']]), verdict='duplicate')
    assert (await provider.validate(tx, third))['state'] == 'denied'
    revised = dict(other, expected_revision=2)
    assert (await provider.validate(tx, revised))['state'] == 'denied'
    assert (await provider.validate(tx, revised))['state'] == 'pending'


def test_png_validation():
    import struct
    import zlib
    module = next(m for m in discover(MODULES) if m.id == 'L02.private-review')
    validate = module.load('listing_review.py:validate_png')
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    photo = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0\0\0\0')) + chunk(b'IEND', b'')
    validate(photo)
    for invalid in (photo[:-1], photo + b'extra', photo.replace(b'IDAT', b'acTL')):
        with pytest.raises(ValueError):
            validate(invalid)
