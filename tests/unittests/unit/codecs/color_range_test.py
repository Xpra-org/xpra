#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.str_fn import memoryview_to_bytes, hexstr
from xpra.util.objects import typedict
from xpra.codecs import loader
from xpra.codecs.image import ImageWrapper
from xpra.codecs.checks import make_test_image


# pixel in RGBX order:
TEST_DATA = {
    "black": "000000ff",
    "white": "ffffffff",
    "green": "00ff00ff",
    "red": "ff0000ff",
    "blue": "0000ffff",
    "cyan": "00ffffff",
    "magenta": "ff00ffff",
    "yellow": "ffff00ff",
}


def cmp_pixels(img1, img2, tolerance=1) -> bool:
    # compare the first 4 pixels:
    for i in range(16):
        b1 = img1[i]
        b2 = img2[i]
        delta = abs(b2-b1)
        if delta > tolerance:
            print(f"pixel {i}: {b1} vs {b2}, {delta}>{tolerance}")
            return False
    return True


class TestColorRange(unittest.TestCase):

    def test_save_rgb(self):
        width = 48
        height = 32
        for enc_name in loader.ENCODER_CODECS:
            enc_mod = loader.load_codec(enc_name)
            if not enc_mod:
                continue
            formats = enc_mod.get_encodings()
            for fmt in formats:
                for color, pixel in TEST_DATA.items():
                    rgb_format = "BGRX"
                    image = make_test_image(rgb_format, width, height, pixel)
                    pixels = image.get_pixels()

                    def cmpimage(other: ImageWrapper, tolerance=1) -> bool:
                        other_pixels = memoryview_to_bytes(memoryview(other.get_pixels()))
                        cmp = cmp_pixels(pixels, other_pixels, tolerance)
                        if not cmp:
                            print(f"expected {hexstr(pixels[:16])} but got {hexstr(other_pixels[:16])}")
                        return cmp

                    for quality, tolerance in {
                        "100": 1 if (enc_name in ("enc_pillow", "enc_jpeg") and fmt in ("webp", "jpeg")) else 0,
                        "90": 3 if (enc_name == "enc_pillow") else 2,
                        "50": 6,
                        "10": 16,
                    }.items():
                        enc_options = typedict({"quality": quality})
                        bdata = enc_mod.encode(fmt, image, options=enc_options)
                        # tuple[str, Compressed, dict[str, Any], int, int, int, int]
                        if not bdata:
                            raise RuntimeError(f"failed to encode {image} using {enc_mod.encode}")
                        file_data = memoryview_to_bytes(bdata[1].data)
                        ext = fmt.replace("/", "")  # ie: "png/L" -> "pngL"
                        filename = f"./{enc_name}-{color}.{ext}"
                        if ext in ("png", "webp", "jpeg"):
                            # verify compressed image with Pillow:
                            from io import BytesIO
                            from PIL import Image
                            img = Image.open(BytesIO(file_data))
                            img = img.convert("RGBA")
                            rdata = img.tobytes("raw", rgb_format.replace("X", "A"))
                            if not cmp_pixels(pixels, rdata, tolerance):
                                raise RuntimeError(f"pixels reloaded from {filename} do not match:"
                                                   f"expected {hexstr(pixels[:16])} but got {hexstr(rdata[:16])}"
                                                   f"with {enc_options=}")
                        # try to decompress to rgb:
                        for dec_name in loader.DECODER_CODECS:
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
                            if not cmpimage(rimage, dec_tolerance):
                                raise RuntimeError(f"decoder {dec_name} produced an image that differs")

                        # try to decompress to yuv
                        for dec_name in loader.DECODER_CODECS:
                            dec_mod = loader.load_codec(dec_name)
                            if not dec_mod:
                                continue
                            if fmt not in dec_mod.get_encodings():
                                continue
                            decompress_to_yuv = getattr(dec_mod, "decompress_to_yuv", None)
                            if not decompress_to_yuv:
                                continue
                            dec_tolerance = tolerance
                            if dec_name == "dec_jpeg":
                                dec_tolerance += 1
                            dec_options = typedict()
                            yuv_image = decompress_to_yuv(file_data, dec_options)
                            assert yuv_image
                            yuv_format = yuv_image.get_pixel_format()
                            # find a csc module to convert this back to rgb:
                            for csc_name in loader.CSC_CODECS:
                                csc_mod = loader.load_codec(csc_name)
                                if not csc_mod:
                                    continue
                                if yuv_format not in csc_mod.get_input_colorspaces():
                                    continue
                                if rgb_format not in csc_mod.get_output_colorspaces(yuv_format):
                                    continue
                                cs_range = "full" if yuv_image.get_full_range() else "studio"
                                csc_options = typedict({"ranges": (cs_range, )})
                                converter = csc_mod.Converter()
                                converter.init_context(width, height, yuv_format,
                                                       width, height, rgb_format, csc_options)
                                rgb_image = converter.convert_image(yuv_image)
                                assert rgb_image
                                if not cmpimage(rgb_image, dec_tolerance + 1):
                                    raise RuntimeError(f"decoder {dec_name} produced a YUV image that differs"
                                                       f" (converted to {rgb_format} from {yuv_format} using {csc_name})")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
