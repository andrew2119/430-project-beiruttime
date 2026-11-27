"""Private image storage checks using actual encoded bytes."""
import importlib.util
from io import BytesIO
from pathlib import Path
import unittest
from PIL import Image, PngImagePlugin
from bt_contracts_core.errors import PublicError

MODULES = Path('/app/modules')
if not MODULES.is_dir():
    MODULES = Path(__file__).resolve().parents[4] / 'services/service-operations/modules'


spec = importlib.util.spec_from_file_location('intake_photo', MODULES / 'intake/photo.py')
photo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(photo)


class PrivatePhotos(unittest.TestCase):
    def test_declared_image_dependency_is_discoverable(self):
        import json
        from bt_runtime.modules import discover
        manifest = MODULES / 'intake/module.json'
        dependencies = json.loads(manifest.read_text())['dependencies']
        self.assertIn('Pillow', dependencies)
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
