"""A deliberately narrow PNG reference policy; no URLs, SVG, animation or metadata."""

import struct
import zlib
from bt_contracts_core.errors import PublicError


def safe_png(content: bytes) -> bytes:
    def reject():
        raise PublicError(
            "unsafe_reference", "Use a non-interlaced, 8-bit PNG under 1 MiB and 2048 pixels per side.", status=422
        )

    if not 0 < len(content) <= 1048576 or content[:8] != b"\x89PNG\r\n\x1a\n":
        reject()
    offset, chunks, compressed, width, height, channels = 8, [], bytearray(), 0, 0, 0
    ended = False
    while offset < len(content):
        if offset + 12 > len(content) or ended:
            reject()
        size = struct.unpack(">I", content[offset : offset + 4])[0]
        kind = content[offset + 4 : offset + 8]
        end = offset + 12 + size
        if end > len(content):
            reject()
        data = content[offset + 8 : offset + 8 + size]
        crc = struct.unpack(">I", content[end - 4 : end])[0]
        if zlib.crc32(kind + data) & 0xFFFFFFFF != crc:
            reject()
        if kind == b"IHDR":
            if chunks or size != 13:
                reject()
            width, height, bits, mode, compression, filtering, interlace = struct.unpack(">IIBBBBB", data)
            channels = {0: 1, 2: 3, 6: 4}.get(mode, 0)
            if (
                not (0 < width <= 2048 and 0 < height <= 2048 and width * height <= 1048576)
                or bits != 8
                or not channels
                or compression
                or filtering
                or interlace
            ):
                reject()
        elif kind == b"IDAT":
            if not width:
                reject()
            compressed.extend(data)
        elif kind == b"IEND":
            if size or not compressed:
                reject()
            ended = True
        else:
            # Reject all metadata/unknown chunks, not just active image formats.
            reject()
        chunks.append(content[offset:end])
        offset = end
    if not ended:
        reject()
    expected = height * (1 + width * channels)
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(bytes(compressed), expected + 1)
        if len(pixels) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            reject()
        stride = 1 + width * channels
        if any(pixels[i] > 4 for i in range(0, len(pixels), stride)):
            reject()
    except zlib.error:
        reject()
    return content[:8] + b"".join(chunks)
