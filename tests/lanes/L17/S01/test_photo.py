"""Private image storage checks using actual encoded bytes."""
import importlib.util
import json
from io import BytesIO
from pathlib import Path
import unittest
from PIL import Image, PngImagePlugin
from bt_contracts_core.errors import PublicError

INTAKE = Path(__file__).resolve().parents[4] / 'services/service-operations/modules/intake'
spec = importlib.util.spec_from_file_location('intake_photo', INTAKE / 'photo.py')
photo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(photo)


class PrivatePhotos(unittest.TestCase):
    def test_optional_image_support_does_not_block_discovery(self):
        from bt_runtime.modules import discover
        manifest = Path(__file__).resolve().parents[4] / 'services/service-operations/modules/intake/module.json'
        dependencies = json.loads(manifest.read_text())['dependencies']
        self.assertNotIn('Pillow', dependencies)
        self.assertEqual([module.id for module in discover(manifest.parent)], ['L09.intake'])

    def test_strips_metadata_for_each_supported_image(self):
        for mime, encoding in [('image/png', 'PNG'), ('image/jpeg', 'JPEG'), ('image/webp', 'WEBP')]:
            with self.subTest(mime=mime):
                output = BytesIO()
                image = Image.new('RGB', (8, 8), 'red')
                exif = Image.Exif()
                exif[270] = 'private source details'
                metadata = PngImagePlugin.PngInfo()
                metadata.add_text('private', 'private source details')
                image.save(output, format=encoding, exif=exif, **({'pnginfo': metadata} if encoding == 'PNG' else {}))
                stored = photo.strip_metadata(output.getvalue(), mime, True)
                with Image.open(BytesIO(stored)) as clean:
                    self.assertEqual(clean.size, (8, 8))
                    self.assertFalse(clean.getexif())
                    self.assertNotIn('private', clean.info)
                self.assertNotIn(b'private source details', stored)

    def test_missing_declaration_corrupt_and_mismatched_images_deny(self):
        output = BytesIO()
        Image.new('RGB', (2, 2)).save(output, format='PNG')
        for content, mime, declared in [(output.getvalue(), 'image/png', False),
                (b'\x89PNG\r\n\x1a\ncorrupt', 'image/png', True),
                (output.getvalue(), 'image/jpeg', True)]:
            with self.assertRaises(PublicError):
                photo.strip_metadata(content, mime, declared)

    def test_missing_image_support_leaves_upload_unavailable(self):
        from unittest.mock import patch
        from fastapi import HTTPException
        import builtins
        original = builtins.__import__
        def without_images(name, *args, **kwargs):
            if name == 'PIL':
                raise ImportError('optional image support unavailable')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=without_images):
            with self.assertRaises(HTTPException) as error:
                photo.strip_metadata(b'synthetic-image', 'image/png', True)
            self.assertEqual(error.exception.status_code, 503)


class IntakePhotoRoute(unittest.IsolatedAsyncioTestCase):
    async def test_current_upload_requires_declaration_and_stores_clean_pixels(self):
        from base64 import b64encode
        from hashlib import sha256
        from contextlib import asynccontextmanager
        from sys import modules
        from types import SimpleNamespace
        from unittest.mock import patch
        from uuid import UUID

        import httpx
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from bt_runtime.modules import discover

        root = Path(__file__).resolve().parents[4]
        module = discover(root / 'services/service-operations/modules/intake')[0]
        upload = module.load('current_evidence.py:upload')
        actor, business, order, record = (UUID(int=value) for value in range(1, 5))
        evidence = modules[upload.__module__]
        caller = SimpleNamespace(actor=SimpleNamespace(subject_id=actor))
        granted = True
        saved = []
        receipts = {}

        class Transaction:
            async def fetchrow(self, statement, *args):
                if 'FROM technical_intakes' in statement:
                    test_case.assertEqual(args, (record, business))
                    return {'order_id': order, 'revision': 1, 'state': 'awaiting_intake', 'private_record': '{"currency":"USD"}'}
                if 'FROM technical_intake_operations' in statement:
                    return receipts.get(args[2])
                return None

            async def fetchval(self, statement, *args):
                return 0 if 'count(*)' in statement else None

            async def execute(self, statement, *args):
                if statement.startswith('INSERT INTO technical_intake_evidence'):
                    saved.append(args[5])
                elif statement.startswith('INSERT INTO technical_intake_operations'):
                    receipts[args[2]] = {'request_hash': args[3], 'result': args[4]}

        test_case = self

        @asynccontextmanager
        async def transaction(*args, **kwargs):
            yield Transaction()

        async def principal():
            return caller

        async def organization(*args):
            return business

        async def record_access(actor_id, organization_id, order_id, permission):
            self.assertEqual((actor_id, organization_id, order_id, permission),
                             (actor, business, order, 'write'))
            return dict(actor_id=actor_id, organization_id=organization_id, order_id=order_id,
                        permission=permission, assignment_revision=1, allowed=granted)

        app = FastAPI()
        app.include_router(module.load('entrypoint.py:router'))
        app.state.pool = None
        app.state.intake_assignments = SimpleNamespace(record_access=record_access)
        app.dependency_overrides[upload.__globals__['principal']] = principal

        @app.exception_handler(PublicError)
        async def failure(request, error):
            return JSONResponse({'error': error.code}, status_code=error.status)

        image = Image.new('RGB', (2, 2), 'red')
        source = BytesIO()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('private', 'synthetic private detail')
        image.save(source, format='PNG', pnginfo=metadata)
        body = {'kind': 'condition_photo', 'media_type': 'image/png',
                'content_base64': b64encode(source.getvalue()).decode('ascii')}
        path = f'/v1/intake/records/{record}/evidence?organization_id={business}&intake_contract=current'
        headers = {'Idempotency-Key': 'test-intake-image', 'If-Match': '1'}

        with patch.multiple(evidence, unit_of_work=transaction, organization=organization):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url='http://example.test') as client:
                unmarked = path.removesuffix('&intake_contract=current')
                missing = await client.post(path, headers=headers, json=body)
                self.assertEqual(missing.status_code, 422)
                self.assertEqual(missing.json()['error'], 'safe_photo_required')
                declared = body | {'safe_photo_declared': True}
                missing = await client.post(unmarked, headers=headers, json=body)
                self.assertEqual((missing.status_code, missing.json()['error']), (422, 'safe_photo_required'))
                self.assertEqual(saved, [])
                granted = False
                self.assertEqual((await client.post(path, headers=headers, json=declared)).status_code, 404)
                self.assertEqual(saved, [])
                granted = True
                result = await client.post(unmarked, headers=headers, json=declared)
                self.assertEqual(result.status_code, 201)
                self.assertEqual(result.json().keys(), {'id', 'record_id', 'revision', 'operation_id', 'organization_id'})
                replay = await client.post(path, headers=headers, json=declared)
                self.assertEqual((replay.status_code, replay.json()), (201, result.json()))

                historical_key = 'test-historical-image'
                historical_result = {'id': str(UUID(int=5)), 'record_id': str(record), 'revision': 2}
                historical_digest = sha256((
                    unmarked.split('?')[0] + '\n1\n' + json.dumps(body, separators=(',', ':'))
                ).encode()).hexdigest()
                receipts[historical_key] = {'request_hash': historical_digest,
                                            'result': json.dumps(historical_result)}
                historical_headers = headers | {'Idempotency-Key': historical_key}
                historical = await client.post(unmarked, headers=historical_headers, json=body)
                self.assertEqual(historical.status_code, 201)
                self.assertEqual(historical.json(), historical_result | {
                    'operation_id': historical_key, 'organization_id': str(business),
                })
                granted = False
                revoked = await client.post(path, headers=historical_headers, json=body)
                self.assertEqual(revoked.status_code, 404)
        self.assertEqual(len(saved), 1)
        self.assertNotIn(b'synthetic private detail', saved[0])
        with Image.open(BytesIO(saved[0])) as clean:
            self.assertEqual(clean.convert('RGB').tobytes(), image.tobytes())
            self.assertNotIn('private', clean.info)


class IntakePrivateReads(unittest.IsolatedAsyncioTestCase):
    async def test_missing_and_unassigned_records_and_evidence_have_identical_responses(self):
        from contextlib import asynccontextmanager
        from sys import modules
        from types import SimpleNamespace
        from unittest.mock import patch
        from uuid import UUID

        import httpx
        from fastapi import FastAPI, HTTPException
        from bt_runtime.modules import discover

        root = Path(__file__).resolve().parents[4]
        module = discover(root / 'services/service-operations/modules/intake')[0]
        from fastapi import APIRouter

        router = APIRouter()
        router.include_router(module.load('entrypoint.py:router'))
        routes = modules[module.load('current_routes.py:detail').__module__]
        evidence = modules[module.load('current_evidence.py:list_evidence').__module__]
        access = modules[module.load('access.py:record_access').__module__]
        record, attachment, missing, order, business = (UUID(int=n) for n in range(1, 6))
        decision = 200
        blob_reads = 0

        class Transaction:
            async def fetchrow(self, statement, resource, organization):
                self_test.assertEqual(organization, business)
                if 'JOIN technical_intakes' in statement:
                    return {'id': attachment, 'order_id': order} if resource == attachment else None
                return {'order_id': order} if resource == record else None

            async def fetchval(self, statement, resource, organization, max_bytes):
                nonlocal blob_reads
                self_test.assertEqual((resource, organization, max_bytes), (attachment, business, 262144))
                blob_reads += 1
                return b'synthetic private condition'

        self_test = self

        @asynccontextmanager
        async def transaction(*args, **kwargs):
            yield Transaction()

        async def organization(*args):
            return business

        async def assignment(p, request, org, order_id, permission):
            self.assertEqual((org, order_id, permission), (business, order, 'read'))
            if decision != 200:
                raise HTTPException(decision)

        async def principal():
            return None

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[routes.principal] = principal
        app.state.pool = SimpleNamespace(acquire=transaction)

        with patch.multiple(routes, organization=organization, unit_of_work=transaction), \
                patch.object(evidence, 'organization', organization), \
                patch.object(access, 'record_access', assignment):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url='http://example.test') as client:
                download = await client.get(f'/v1/intake/evidence/{attachment}')
                self.assertEqual(download.status_code, 200)
                self.assertEqual(download.json()['id'], str(attachment))
                self.assertTrue(download.json()['content_base64'])
                for path, known in (
                    ('/records/{}', record),
                    ('/records/{}/evidence', record),
                    ('/evidence/{}', attachment),
                ):
                    decision = 403
                    absent = await client.get('/v1/intake' + path.format(missing))
                    denied = await client.get('/v1/intake' + path.format(known))
                    self.assertEqual((denied.status_code, denied.json()),
                                     (absent.status_code, absent.json()))
                    for decision in (401, 503):
                        failed = await client.get('/v1/intake' + path.format(known), params={'intake_contract': 'current'})
                        self.assertEqual(failed.status_code, decision)
                self.assertEqual(blob_reads, 1)
