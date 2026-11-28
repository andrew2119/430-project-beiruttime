"""Check that the scripted review's photo input is one complete, plain PNG. Test only.

The scripted actor runs this on the frozen test icon before it offers it; not physical inspection.
"""
import re
import struct
import zlib

from proof_types import digest,require


def photo_observation(raw):
    require(57<=len(raw)<=750*1024 and raw.startswith(b'\x89PNG\r\n\x1a\n'),'private PNG has wrong signature or byte count')
    cursor=8; pixels=bytearray(); shape=None; phase='header'
    while cursor<len(raw):
        n,kind=struct.unpack_from('>I4s',raw,cursor)
        end=cursor+12+n; data=raw[cursor+8:end-4]
        require(end<=len(raw) and re.fullmatch(rb'[A-Za-z]{4}',kind) and zlib.crc32(kind+data)==struct.unpack_from('>I',raw,end-4)[0],
                'private PNG has invalid framing or checksum')
        if phase=='header':
            require(kind==b'IHDR' and n==13,'private PNG lacks first image header')
            w,h,depth,mode,comp,filt,interlace=struct.unpack('>IIBBBBB',data); channels={0:1,2:3,4:2,6:4}.get(mode)
            require(0<w*h<=4_000_000 and depth==8 and channels and (comp,filt,interlace)==(0,0,0),'private PNG image shape is invalid')
            shape=dict(width=w,height=h,channels=channels); phase='ancillary'
        elif kind==b'IDAT':
            require(phase in ('ancillary','pixels'),'private PNG has noncontiguous pixels')
            phase='pixels'; pixels.extend(data)
        elif kind==b'IEND':
            require(phase in ('pixels','tail') and n==0 and end==len(raw),'private PNG end is invalid')
            phase='closed'
        else:
            require(kind not in {b'acTL',b'fcTL',b'fdAT'} and kind[:1].islower(),'unsupported private PNG chunk')
            if phase=='pixels': phase='tail'
        cursor=end
    require(phase=='closed' and pixels,'private PNG does not contain a complete image')
    stride=1+shape['width']*shape['channels']; size=shape['height']*stride
    decode=zlib.decompressobj(); decoded=decode.decompress(pixels,size+1)
    require(len(decoded)==size and decode.eof and not decode.unused_data and all(x<=4 for x in decoded[::stride]),'invalid private PNG pixel data')
    return dict(media='image/png',length=len(raw),sha256=digest(raw),geometry=shape)
