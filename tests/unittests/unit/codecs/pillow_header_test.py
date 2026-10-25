#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import zlib
import struct
import unittest
import binascii

from xpra.codecs.image_type import get_image_type


class TestPillowHeader(unittest.TestCase):

    def test_known_header(self):
        examples = {
            "png"   : "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000c4944415408d763f8ffff3f0005fe02fedccc59e70000000049454e44ae42608227",
            "webp"  : "524946462600000057454250565038201a0000003001009d012a0100010000c01225a400037000fefedd78000000",
            "bmp"   : "424d3a0000000000000036000000280000000100000001000000010018000000000004000000130b0000130b000000000000000000000000ff00",
            "jpeg"  : "ffd8ffe000104a46494600010101012c012c0000fffe00134372656174656420776974682047494d50ffdb0043000302020302020303030304030304050805050404050a070706080c0a0c0c0b0a0b0b0d0e12100d0e110e0b0b1016101113141515150c0f171816141812141514ffdb00430103040405040509050509140d0b0d1414141414141414141414141414141414141414141414141414141414141414141414141414141414141414141414141414ffc00011080001000103011100021101031101ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffc4001f0100030101010101010101010000000000000102030405060708090a0bffc400b51100020102040403040705040400010277000102031104052131061241510761711322328108144291a1b1c109233352f0156272d10a162434e125f11718191a262728292a35363738393a434445464748494a535455565758595a636465666768696a737475767778797a82838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9faffda000c03010002110311003f00fd53a00fffd9",
        }
        for encoding, hexdata in examples.items():
            data = binascii.unhexlify(hexdata)
            e = get_image_type(data)
            assert encoding==e, "expected %s got %s" % (encoding, e)

    def test_svg_with_leading_comment(self):
        comment = b"<!-- Copyright 2000-2024 JetBrains s.r.o. and contributors. " \
                  b"Use of this source code is governed by the Apache 2.0 license. -->\n"
        data = comment + b'<svg width="64" height="64" xmlns="http://www.w3.org/2000/svg"></svg>'
        self.assertEqual(get_image_type(data), "svg")

    def test_apng(self):
        from io import BytesIO
        from PIL import Image
        frames = [Image.new("RGB", (16, 16), color) for color in ("red", "blue")]
        buf = BytesIO()
        frames[0].save(buf, "PNG", save_all=True, append_images=frames[1:])
        apng = buf.getvalue()
        self.assertEqual(get_image_type(apng), "apng")
        self.assertEqual(get_image_type(memoryview(apng)), "apng")
        # the `acTL` chunk can come after other chunks, insert a `tEXt` chunk after `IHDR`:
        text = b"Comment\0" + b"x" * 300
        chunk = struct.pack(">I4s", len(text), b"tEXt") + text + struct.pack(">I", zlib.crc32(b"tEXt" + text))
        ihdr_end = 8 + 12 + 13
        self.assertEqual(get_image_type(apng[:ihdr_end] + chunk + apng[ihdr_end:]), "apng")
        # an ICO file can embed it:
        ico = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 16, 16, 0, 0, 1, 32, len(apng), 6 + 16) + apng
        self.assertEqual(get_image_type(ico), "apng")
        self.assertEqual(get_image_type(memoryview(ico)), "apng")
        # a single frame is a plain png:
        buf = BytesIO()
        frames[0].save(buf, "PNG")
        self.assertEqual(get_image_type(buf.getvalue()), "png")
        # and an ICO with png frames is a plain ICO:
        buf = BytesIO()
        Image.new("RGBA", (256, 256), "red").save(buf, "ICO", sizes=[(256, 256), (16, 16)], bitmap_format="png")
        self.assertEqual(get_image_type(buf.getvalue()), "ico")

        from xpra.codecs.pillow.decoder import open_only
        with self.assertRaises(ValueError):
            open_only(apng)
        with self.assertRaises(ValueError):
            open_only(apng, ("png", ))
        self.assertEqual(open_only(apng, ("apng", )).size, (16, 16))

    def test_pillow_formats(self):
        from io import BytesIO
        from PIL import Image
        img = Image.new("RGB", (16, 16), "red")
        for encoding in ("png", "jpeg", "webp", "bmp", "ico", "ppm", "tiff"):
            buf = BytesIO()
            img.save(buf, encoding)
            self.assertEqual(get_image_type(buf.getvalue()), encoding)

    def test_bad_header(self):
        for x in (b"", None,
                  b"abc",
                  b"\x99PNG",
                  b"RIF",
                  b"RIFF&\x00\x00\x00WEBp",
                  b"BM" + b"\0" * 40,
                  b"\0\0\1\0\0\0" + b"\0" * 32,
                  b"P7 " + b"\0" * 32,
                  b"P6" + b"\0" * 32,
                  binascii.unhexlify("fe0000000000000000000000000000000000000000000000000000"),
                  ):
            if e := get_image_type(x):
                raise RuntimeError(f"wrongly detected {x} as {e}")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
