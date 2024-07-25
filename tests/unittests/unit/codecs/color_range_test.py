#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from collections.abc import Sequence

from xpra.util.str_fn import memoryview_to_bytes, hexstr, sorted_nicely
from xpra.util.objects import typedict
from xpra.codecs import loader
from xpra.codecs.image import ImageWrapper
from xpra.codecs.checks import make_test_image, TEST_COLORS


def cmp_bytes(b1: bytes, b2: bytes, tolerance=1) -> bool:
    length = min(len(b1), len(b2))
    for i in range(length):
        v1 = b1[i]
        v2 = b2[i]
        delta = abs(v2-v1)
        if delta > tolerance:
            print(f"pixel {i} /  {length}: {v1:x} vs {v2:x}, {delta:x}>{tolerance:x}")
            return False
    return True


def cmp_pixels(pix1: bytes, w1: int, h1: int, stride1: int, bpp1: int,
               pix2: bytes, w2: int, h2: int, stride2: int, bpp2: int,
               tolerance=1) -> bool:
    h = min(h1, h2)
    w = min(w1, w2)
    for y in range(h):
        row1 = pix1[y * stride1: y * stride1 + w * bpp1]
        row2 = pix2[y * stride2: y * stride2 + w * bpp2]
        if not cmp_bytes(row1, row2, tolerance):
            print("expected:")
            print(hexstr(row1))
            print("but got:")
            print(hexstr(row2))
            print(f"for row {y} / {h}")
            return False
    return True


def cmp_images(image1: ImageWrapper, image2: ImageWrapper, tolerance=1) -> bool:
    pixels1 = memoryview_to_bytes(memoryview(image1.get_pixels()))
    pixels2 = memoryview_to_bytes(memoryview(image2.get_pixels()))
    return cmp_pixels(
        pixels1, image1.get_width(), image1.get_height(), image1.get_rowstride(), image1.get_bytesperpixel(),
        pixels2, image2.get_width(), image2.get_height(), image2.get_rowstride(), image2.get_bytesperpixel(),
        tolerance)


class TestColorRange(unittest.TestCase):

    def test_encode_decode_range(self) -> None:
        self.do_test_encode_decode_range(loader.ENCODER_CODECS, loader.DECODER_CODECS, loader.CSC_CODECS)

    def do_test_encode_decode_range(self,
                                    encoders: Sequence[str],
                                    decoders: Sequence[str],
                                    csc_modules=Sequence[str]) -> None:
        test_info: set[str] = set()
        width = 48
        height = 32
        for enc_name in encoders:
            enc_mod = loader.load_codec(enc_name)
            if not enc_mod:
                continue
            formats = enc_mod.get_encodings()
            for fmt in formats:
                for color, pixel in TEST_COLORS.items():
                    rgb_format = "BGRX"
                    image = make_test_image(rgb_format, width, height, pixel)
                    pixels = image.get_pixels()

                    for quality, tolerance in {
                        "100": 1 if fmt in ("jpeg", ) else 0,
                        "90": 2 if fmt in ("webp", ) else 1,
                        "50": 4,
                        "10": 0xc if fmt in ("webp", ) else 4,
                    }.items():
                        if enc_name == "enc_pillow" and fmt == "webp":
                            tolerance += 3
                        enc_options = typedict({"quality": quality})
                        bdata = enc_mod.encode(fmt, image, options=enc_options)
                        # tuple[str, Compressed, dict[str, Any], int, int, int, int]
                        if not bdata:
                            raise RuntimeError(f"failed to encode {image} using {enc_mod.encode}")
                        file_data = memoryview_to_bytes(bdata[1].data)
                        ext = fmt.replace("/", "")  # ie: "png/L" -> "pngL"
                        filename = f"./{enc_name}-{color}.{ext}"
                        if ext in ("png", "webp", "jpeg"):
                            # verify first 16 bytes when compressed image with Pillow:
                            from io import BytesIO
                            from PIL import Image
                            img = Image.open(BytesIO(file_data))
                            img = img.convert("RGBA")
                            rdata = img.tobytes("raw", rgb_format.replace("X", "A"))
                            if not cmp_bytes(pixels[:16], rdata[:16], tolerance):
                                raise RuntimeError(f"pixels reloaded from {filename} do not match:"
                                                   f"expected {hexstr(pixels[:16])} but got {hexstr(rdata[:16])} "
                                                   f"with {enc_options=}")
                            test_info.add(f"{enc_name:12}  {fmt:12}  pillow                                    {rgb_format}")

                        # try to decompress to rgb:
                        for dec_name in decoders:
                            dec_mod = loader.load_codec(dec_name)
                            if not dec_mod:
                                continue
                            if fmt not in dec_mod.get_encodings():
                                continue
                            decompress_to_rgb = getattr(dec_mod, "decompress_to_rgb", None)
                            # print(f"testing {fmt} rgb decoding using {decompress_to_rgb}")
                            if not decompress_to_rgb:
                                continue
                            rimage = decompress_to_rgb(rgb_format, file_data)
                            dec_tolerance = tolerance
                            if dec_name == "dec_jpeg":
                                dec_tolerance += 1
                            if not cmp_images(image, rimage, dec_tolerance):
                                raise RuntimeError(f"decoder {dec_name} from {enc_name} produced an image that differs with {enc_options=}")
                            test_info.add(f"{enc_name:12}  {fmt:12}  {dec_name:12}                              {rgb_format}")

                        # try to decompress to yuv
                        for dec_name in decoders:
                            dec_mod = loader.load_codec(dec_name)
                            if not dec_mod:
                                continue
                            if fmt not in dec_mod.get_encodings():
                                continue
                            decompress_to_yuv = getattr(dec_mod, "decompress_to_yuv", None)
                            if not decompress_to_yuv:
                                continue
                            dec_tolerance = tolerance + 2
                            dec_options = typedict()
                            yuv_image = decompress_to_yuv(file_data, dec_options)
                            assert yuv_image
                            yuv_format = yuv_image.get_pixel_format()
                            # find a csc module to convert this back to rgb:
                            for csc_name in csc_modules:
                                csc_mod = loader.load_codec(csc_name)
                                if not csc_mod:
                                    continue
                                if yuv_format not in csc_mod.get_input_colorspaces():
                                    continue
                                if rgb_format not in csc_mod.get_output_colorspaces(yuv_format):
                                    continue
                                csc_options = typedict({"full-range": yuv_image.get_full_range()})
                                converter = csc_mod.Converter()
                                converter.init_context(width, height, yuv_format,
                                                       width, height, rgb_format, csc_options)
                                rgb_image = converter.convert_image(yuv_image)
                                assert rgb_image
                                if not cmp_images(image, rgb_image, dec_tolerance):
                                    raise RuntimeError(f"decoder {dec_name} from {enc_name} produced a YUV image that differs with {enc_options=}"
                                                       f" (converted to {rgb_format} from {yuv_format} using {csc_name})")
                                test_info.add(f"{enc_name:12}  {fmt:12}  {dec_name:12}  {yuv_format:12}  {csc_name:12}  {rgb_format:12}")
        print(f"successfully tested {rgb_format} input with:")
        for s in sorted_nicely(test_info):
            print(f"{s}")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
