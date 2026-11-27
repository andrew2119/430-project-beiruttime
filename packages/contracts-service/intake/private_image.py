"""Decode bounded private images and store only fresh pixel encodings."""
from io import BytesIO
import warnings
from fastapi import HTTPException
from bt_contracts_core.errors import PublicError


def strip_metadata(content, media_type, declared):
    if declared is not True:
        raise PublicError('safe_photo_required', 'Confirm the safe-photo declaration.', status=422)
    try:
        from PIL import Image
    except ImportError:
        raise HTTPException(503) from None
    formats = {'image/jpeg': 'JPEG', 'image/png': 'PNG', 'image/webp': 'WEBP'}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format != formats[media_type] or image.width * image.height > 16000000 or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('invalid_image')
                image.load()
                mode = 'RGB' if media_type == 'image/jpeg' else 'RGBA'
                converted = image.convert(mode)
                clean = Image.frombytes(mode, converted.size, converted.tobytes())
                output = BytesIO()
                clean.save(output, format=formats[media_type])
                result = output.getvalue()
                if not 1 <= len(result) <= 262144:
                    raise ValueError('invalid_image')
                return result
    except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise PublicError('invalid_evidence', 'Supply a supported private image.', status=422) from None
