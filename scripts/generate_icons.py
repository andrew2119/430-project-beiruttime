"""Generate original watch-dial PNG icons without image-library dependencies."""
from pathlib import Path
import math
import struct
import zlib


def png(size):
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            dx, dy = (x+.5)/size-.5, (y+.5)/size-.5
            radius = math.hypot(dx, dy)
            color = (23,60,52)
            if .305 < radius < .32:
                color = (217,197,157)
            angle = math.atan2(dy,dx)
            tick = abs(((angle + math.pi/2) / (math.pi/6) + .5) % 1 - .5)
            if .265 < radius < .29 and tick < .025:
                color = (217,197,157)
            # Dial hands towards 10 and 2; bounded central geometry preserves maskable safe zone.
            if abs(dy-dx) < .009 and -.16 < dx < .01 or abs(dy+dx) < .008 and 0 < dx < .20 or radius < .018:
                color = (217,197,157)
            rows.extend(color)
    def chunk(kind,data):
        return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',size,size,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows,9))+chunk(b'IEND',b'')

root=Path(__file__).resolve().parents[1]/'web/public/icons'
root.mkdir(parents=True,exist_ok=True)
for name,size in [('bt-192',192),('bt-512',512),('bt-maskable',512)]:
    (root/f'{name}.png').write_bytes(png(size))
