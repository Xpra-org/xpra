#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

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


def get_tolerance(enc_name: str, encoding: str, quality: int) -> int:
    tolerance = {
        100: 1 if encoding in ("jpeg",) else 0,
        90: 2 if encoding in ("webp",) else 1,
        50: 4,
        10: 0xc if encoding in ("webp",) else 4,
    }.get(quality, 0)
    if enc_name == "enc_pillow" and encoding == "webp":
        tolerance += 3
    return tolerance


class TestColorRange(unittest.TestCase):

    def setUp(self) -> None:
        self.width = 48
        self.height = 32
        self.rgb_format = "BGRX"
        self.test_info: set[str] = set()

    def tearDown(self) -> None:
        print(f"successfully tested {self.rgb_format} input with:")
        for s in sorted_nicely(self.test_info):
            print(f"{s}")

    def test_pseudo_video(self) -> None:
        self.do_test_pseudo_video("enc_webp", "webp")
        self.do_test_pseudo_video("enc_jpeg", "jpeg")

    def do_test_pseudo_video(self, enc_name: str, encoding: str) -> None:
        enc_mod = loader.load_codec(enc_name)
        for color, pixel in TEST_COLORS.items():
            image = make_test_image(self.rgb_format, self.width, self.height, pixel)
            self.pixels = image.get_pixels()
            for quality in (100, 90, 50, 10):
                tolerance = get_tolerance(enc_name, encoding, quality)
                options = typedict({
                    "quality": quality,
                    "color": color,
                    "tolerance": tolerance,
                })
                encoder = enc_mod.Encoder()
                encoder.init_context(encoding, self.width, self.height, self.rgb_format, typedict())
                data, client_options = encoder.compress_image(image, options=options)
                bdata = memoryview_to_bytes(data)
                self.verify_PIL(enc_name, encoding, image, options, bdata)
                self.verify_rgb(enc_name, encoding, image, options, bdata)
                self.verify_yuv(enc_name, encoding, image, options, bdata, client_options)

    def test_encode_decode_range(self) -> None:
        encoders = os.environ.get("XPRA_TEST_ENCODERS", ",".join(loader.ENCODER_CODECS)).split(",")
        for enc_name in encoders:
            enc_mod = loader.load_codec(enc_name)
            if not enc_mod:
                continue
            formats = enc_mod.get_encodings()
            for encoding in formats:
                for color, pixel in TEST_COLORS.items():
                    image = make_test_image(self.rgb_format, self.width, self.height, pixel)
                    # the encoder may modify the pixels value,
                    # (the spng encoder does)
                    self.pixels = image.get_pixels()
                    for quality in (100, 90, 50, 10):
                        tolerance = get_tolerance(enc_name, encoding, quality)
                        options = typedict({
                            "quality": quality,
                            "color": color,
                            "tolerance": tolerance,
                        })
                        output = enc_mod.encode(encoding, image, options=options)
                        # tuple[str, Compressed, dict[str, Any], int, int, int, int]
                        if not output:
                            raise RuntimeError(f"failed to encode {image} using {enc_mod.encode}")
                        bdata = memoryview_to_bytes(output[1].data)
                        client_options = output[2]
                        self.verify_PIL(enc_name, encoding, image, options, bdata)
                        self.verify_rgb(enc_name, encoding, image, options, bdata)
                        self.verify_yuv(enc_name, encoding, image, options, bdata, client_options)

    def verify_PIL(self, enc_name: str, encoding: str, image: ImageWrapper, enc_options: dict, data: bytes) -> None:
        ext = encoding.replace("/", "")  # ie: "png/L" -> "pngL"
        if ext not in ("png", "webp", "jpeg"):
            return
        # verify first 16 bytes when compressed image with Pillow:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(data))
        img = img.convert("RGBA")
        rdata = img.tobytes("raw", self.rgb_format.replace("X", "A"))
        tolerance = enc_options["tolerance"]
        bpp = len(self.rgb_format)
        # one pixel at a time:
        for pix_x in range(self.width):
            # test each component individually: 'R', 'G' and 'B'
            for i, component in enumerate(self.rgb_format):
                if component in ("X", "A"):
                    continue
                index = pix_x * bpp + i
                v1 = self.pixels[index]
                v2 = rdata[index]
                if abs(v1 - v2) > tolerance:
                    raise RuntimeError(f"pixels reloaded do not match: "
                                       f"expected {hexstr(self.pixels[:16])} but got {hexstr(rdata[:16])} "
                                       f"from {enc_name} using {encoding} and pixel format {self.rgb_format} "
                                       f"with {enc_options=} "
                                       f"mismatch at pixel {pix_x} for component {i}: {component}: {v1:x} vs {v2:x} "
                                       f"tolerance={tolerance}")
        self.test_info.add(f"{enc_name:12}  {encoding:12}  pillow                                    {self.rgb_format}")

    def verify_rgb(self, enc_name: str, encoding: str, image: ImageWrapper, enc_options: dict, data: bytes) -> None:
        # try to decompress to rgb:
        decoders = os.environ.get("XPRA_TEST_DECODERS", ",".join(loader.DECODER_CODECS)).split(",")
        for dec_name in decoders:
            dec_mod = loader.load_codec(dec_name)
            if not dec_mod:
                continue
            if encoding not in dec_mod.get_encodings():
                continue
            decompress_to_rgb = getattr(dec_mod, "decompress_to_rgb", None)
            # print(f"testing {fmt} rgb decoding using {decompress_to_rgb}")
            if not decompress_to_rgb:
                continue
            dec_options = typedict({"rgb_format": self.rgb_format})
            rimage = decompress_to_rgb(data, dec_options)
            tolerance = enc_options["tolerance"]
            if dec_name == "dec_jpeg":
                tolerance += 1
            if not cmp_images(image, rimage, tolerance):
                raise RuntimeError(f"decoder {dec_name} from {enc_name} produced an image that differs with {enc_options=}")
            self.test_info.add(f"{enc_name:12}  {encoding:12}  {dec_name:12}                              {self.rgb_format}")

    def verify_yuv(self, enc_name: str, encoding: str, image: ImageWrapper, enc_options: dict, data: bytes, client_options: dict) -> None:
        decoders = os.environ.get("XPRA_TEST_DECODERS", ",".join(loader.DECODER_CODECS)).split(",")
        csc_modules = os.environ.get("XPRA_TEST_CSC", ",".join(loader.CSC_CODECS)).split(",")
        # try to decompress to yuv
        for dec_name in decoders:
            dec_mod = loader.load_codec(dec_name)
            if not dec_mod:
                continue
            if encoding not in dec_mod.get_encodings():
                continue
            decompress_to_yuv = getattr(dec_mod, "decompress_to_yuv", None)
            if not decompress_to_yuv:
                continue
            dec_options = typedict(client_options)
            yuv_image = decompress_to_yuv(data, dec_options)
            assert yuv_image
            yuv_format = yuv_image.get_pixel_format()
            # find a csc module to convert this back to rgb:
            for csc_name in csc_modules:
                csc_mod = loader.load_codec(csc_name)
                if not csc_mod:
                    continue

                def find_spec():
                    for spec in csc_mod.get_specs():
                        if yuv_format not in spec.input_colorspace:
                            continue
                        if self.rgb_format not in spec.output_colorspaces:
                            continue
                        return spec
                    return None

                spec = find_spec()
                csc_options = typedict({"full-range": yuv_image.get_full_range()})
                converter = spec.codec_class()
                converter.init_context(self.width, self.height, yuv_format,
                                       self.width, self.height, self.rgb_format, csc_options)
                rgb_image = converter.convert_image(yuv_image)
                assert rgb_image
                tolerance = enc_options["tolerance"]
                if not cmp_images(image, rgb_image, tolerance + 2):
                    raise RuntimeError(f"decoder {dec_name} from {enc_name} produced a YUV image that differs with {enc_options=}"
                                       f" (converted to {self.rgb_format} from {yuv_format} using {csc_name})")
                self.test_info.add(f"{enc_name:12}  {encoding:12}  {dec_name:12}  {yuv_format:12}  {csc_name:12}  {self.rgb_format:12}")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
