"""Measured bytes, decoded pixels, metadata-free variants."""

import io
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError
from bt_contracts_core.errors import PublicError

MAX_BYTES = 8_000_000
MAX_PIXELS = 20_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def attribution_matches(content, credit):
    markers = {"author": "Author: ", "source_url": "Source: ", "license_url": "License: ", "license": "License name: "}
    return all(
        isinstance(credit.get(field), str)
        and 0 < len(credit[field]) < 1000
        and "\n" not in credit[field]
        and "\r" not in credit[field]
        and (label + credit[field] + "\n").encode("utf-8") in content
        for field, label in markers.items()
    )


def normalize(content):
    if not content or len(content) > MAX_BYTES:
        raise PublicError("media_bytes_limit", "Image exceeds the upload budget.", status=413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as probe:
                if probe.format not in ("JPEG", "PNG") or probe.width * probe.height > MAX_PIXELS:
                    raise ValueError("Unsupported image or pixel budget")
                if getattr(probe, "n_frames", 1) != 1:
                    raise ValueError("Animated image")
                probe.verify()
            with Image.open(io.BytesIO(content)) as source:
                source.load()
                oriented = ImageOps.exif_transpose(source)
                # A new pixel-only image removes EXIF, comments, profiles and serial metadata.
                image = Image.new("RGB", oriented.size, (255, 255, 255))
                if oriented.mode in ("RGBA", "LA"):
                    rgba = oriented.convert("RGBA")
                    image.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    image.paste(oriented.convert("RGB"))
        variants = {}
        for label, edge in (("thumb", 320), ("card", 640), ("detail", 1600)):
            resized = image.copy()
            resized.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            target = io.BytesIO()
            resized.save(target, format="JPEG", quality=85, optimize=True)
            variants[label] = {"content": target.getvalue(), "width": resized.width, "height": resized.height}
        return variants
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise PublicError(
            "invalid_image", "Use a valid, non-animated JPEG or PNG within the pixel budget.", status=422
        ) from None
