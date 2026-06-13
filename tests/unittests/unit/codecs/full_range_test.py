#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import typedict
from xpra.util.str_fn import memoryview_to_bytes, sorted_nicely
from xpra.codecs import loader
from xpra.codecs.checks import make_test_image, TEST_COMPRESSED_DATA

# "studio" (aka "limited" / "tv") swing maps 8-bit luma to roughly [16..235],
# "full" (aka "pc") swing maps it to [0..255].
# the luma values we expect to find for a fully black and a fully white pixel,
# for each range (a few codecs round the studio white differently, hence the tolerance):
RANGE_LUMA = {
    True: {"black": 0x00, "white": 0xFF},   # full-range
    False: {"black": 0x10, "white": 0xEB},  # studio-range
}
LUMA_TOLERANCE = 2

# RGB pixels (in BGRX byte order, the alpha/X byte is ignored for luma):
TEST_LUMA_COLORS = {
    "black": "000000ff",
    "white": "ffffffff",
}

# Video decoders which read the colour range from the encoded bitstream
# instead of honouring the "full-range" decode option passed by the caller.
# For these, the option must be *ignored* and the result is whatever the
# sample stream was encoded with (all our samples are studio-range):
BITSTREAM_RANGE_DECODERS = ("dec_aom", )

# Codecs which do not signal the colour range at all
# (there is nothing to verify and exercising them here is slow/flaky):
NO_RANGE_CODECS = ("enc_gstreamer", "dec_gstreamer")

TEST_SIZE = 128, 128


def first_luma(image) -> int:
    # the first byte of the first (Y) plane:
    return memoryview_to_bytes(image.get_pixels()[0])[0]


def find_spec(specs, in_cs: str, out_cs: str):
    for spec in specs:
        if spec.input_colorspace == in_cs and out_cs in spec.output_colorspaces:
            return spec
    return None


class FullRangeCSCTest(unittest.TestCase):
    """ verify that the CSC modules honour and preserve the "full-range" flag """

    def test_rgb_to_yuv_full_range(self):
        width = height = 32
        rgb_format = "BGRX"
        yuv_format = "YUV420P"
        tested: list[str] = []
        for csc_name in loader.CSC_CODECS:
            csc_mod = loader.load_codec(csc_name)
            if not csc_mod:
                continue
            spec = find_spec(csc_mod.get_specs(), rgb_format, yuv_format)
            if not spec:
                continue
            for full_range in (True, False):
                expected = RANGE_LUMA[full_range]
                for color, pixel in TEST_LUMA_COLORS.items():
                    converter = spec.codec_class()
                    options = typedict({"full-range": full_range})
                    converter.init_context(width, height, rgb_format,
                                           width, height, yuv_format, options)
                    try:
                        image = make_test_image(rgb_format, width, height, pixel)
                        out = converter.convert_image(image)
                    finally:
                        converter.clean()
                    # the flag must be preserved on the output image,
                    # so the decoder side knows how to interpret the planes:
                    self.assertEqual(bool(out.get_full_range()), full_range,
                                     f"{csc_name}: {rgb_format}->{yuv_format} output full-range flag"
                                     f" is {bool(out.get_full_range())}, expected {full_range}")
                    # and the conversion must actually use the requested range:
                    luma = first_luma(out)
                    want = expected[color]
                    self.assertLessEqual(
                        abs(luma - want), LUMA_TOLERANCE,
                        f"{csc_name}: {color} luma for full-range={full_range} is 0x{luma:02x},"
                        f" expected 0x{want:02x} (+/-{LUMA_TOLERANCE})")
            tested.append(csc_name)
        self._report(tested)
        if not tested:
            self.skipTest("no CSC module able to convert BGRX to YUV420P")

    def test_full_and_studio_differ(self):
        # converting the very same pixel with and without full-range
        # must yield different luma values, otherwise the flag is ignored:
        width = height = 32
        rgb_format = "BGRX"
        yuv_format = "YUV420P"
        tested: list[str] = []
        for csc_name in loader.CSC_CODECS:
            csc_mod = loader.load_codec(csc_name)
            if not csc_mod:
                continue
            spec = find_spec(csc_mod.get_specs(), rgb_format, yuv_format)
            if not spec:
                continue
            luma = {}
            for full_range in (True, False):
                converter = spec.codec_class()
                converter.init_context(width, height, rgb_format,
                                       width, height, yuv_format,
                                       typedict({"full-range": full_range}))
                try:
                    image = make_test_image(rgb_format, width, height, "000000ff")
                    out = converter.convert_image(image)
                finally:
                    converter.clean()
                luma[full_range] = first_luma(out)
            self.assertNotEqual(luma[True], luma[False],
                                f"{csc_name}: black luma is identical (0x{luma[True]:02x})"
                                f" for full-range and studio-range - the flag is ignored")
            tested.append(csc_name)
        self._report(tested)
        if not tested:
            self.skipTest("no CSC module able to convert BGRX to YUV420P")

    def _report(self, tested) -> None:
        print(f"tested full-range CSC handling with: {sorted_nicely(tested)}")


class FullRangeEncoderTest(unittest.TestCase):
    """ verify that the video encoders signal the colour range to the decoder
        via the "full-range" client option """

    def test_video_encoders(self):
        tested: list[str] = []
        no_signal: list[str] = []
        skipped: list[str] = []
        for enc_name in loader.ENCODER_VIDEO_CODECS:
            if enc_name in NO_RANGE_CODECS:
                no_signal.append(enc_name)
                continue
            enc_mod = loader.load_codec(enc_name)
            if not enc_mod:
                continue
            signalled = False
            compressed = False
            for spec in enc_mod.get_specs():
                in_cs = spec.input_colorspace
                for full_range in (True, False):
                    client_options = self._encode(enc_name, spec, in_cs, full_range, skipped)
                    if client_options is None:
                        continue
                    compressed = True
                    if "full-range" not in client_options:
                        continue
                    signalled = True
                    reported = client_options.get("full-range")
                    # encoders that cannot produce full-range output (spec.full_range is False)
                    # are locked to studio-range regardless of the input image,
                    # every other encoder must report back the range of the image it was given:
                    expected = full_range and bool(spec.full_range)
                    self.assertEqual(
                        bool(reported), expected,
                        f"{enc_name}: {spec.encoding} reported full-range={bool(reported)} for an"
                        f" image with full-range={full_range} (spec.full_range={spec.full_range})")
            if signalled:
                tested.append(enc_name)
            elif compressed:
                # the encoder ran but never put a "full-range" flag in its client options:
                no_signal.append(enc_name)
        print(f"tested full-range signalling with encoders: {sorted_nicely(tested)}")
        if no_signal:
            print(f"encoders that do not signal the colour range: {sorted_nicely(no_signal)}")
        if skipped:
            print(f"skipped (unavailable at runtime): {sorted_nicely(skipped)}")
        if not tested:
            self.skipTest("no video encoder able to signal the colour range")

    def _encode(self, enc_name, spec, in_cs: str, full_range: bool, skipped: list):
        # returns the client options the encoder produced, or None if it could not run
        w, h = TEST_SIZE
        try:
            image = make_test_image(in_cs, w, h)
        except ValueError:
            # no test image for this input colorspace
            return None
        image.set_full_range(full_range)
        encoder = spec.codec_class()
        try:
            options = typedict({
                "full-range": full_range,
                "dst-formats": list(spec.output_colorspaces),
                "quality": 50,
                "speed": 50,
            })
            encoder.init_context(spec.encoding, w, h, in_cs, options)
            out = encoder.compress_image(image, typedict())
        except Exception as e:
            # hardware encoders may not be usable on this host:
            skipped.append(f"{enc_name}:{spec.encoding}:{in_cs} ({e})")
            return None
        finally:
            encoder.clean()
        if not out:
            skipped.append(f"{enc_name}:{spec.encoding}:{in_cs} (no data)")
            return None
        return out[1]


class FullRangeDecoderTest(unittest.TestCase):
    """ verify that the video decoders apply the colour range:
        most honour the "full-range" decode option,
        a few derive it from the encoded bitstream instead """

    def test_video_decoders(self):
        tested: list[str] = []
        skipped: list[str] = []
        for dec_name in loader.DECODER_VIDEO_CODECS:
            if dec_name in NO_RANGE_CODECS:
                continue
            dec_mod = loader.load_codec(dec_name)
            if not dec_mod:
                continue
            from_bitstream = dec_name in BITSTREAM_RANGE_DECODERS
            decoded_any = False
            for spec in dec_mod.get_specs():
                encoding = spec.encoding
                cs = spec.input_colorspace
                size, frames = self._find_sample(dec_mod, encoding, cs)
                if not frames:
                    continue
                results = {}
                for full_range in (True, False):
                    image = self._decode(dec_mod, dec_name, encoding, cs, size, frames, full_range, skipped)
                    if image is None:
                        results = {}
                        break
                    results[full_range] = bool(image.get_full_range())
                if not results:
                    continue
                decoded_any = True
                if from_bitstream:
                    # the option must be ignored: both runs yield the stream's range:
                    self.assertEqual(
                        results[True], results[False],
                        f"{dec_name}: {encoding} colour range changed with the decode option"
                        f" but should come from the bitstream ({results})")
                else:
                    for full_range, got in results.items():
                        self.assertEqual(
                            got, full_range,
                            f"{dec_name}: {encoding} produced full-range={got}"
                            f" when decoding with the full-range={full_range} option")
            if decoded_any:
                tested.append(dec_name)
        print(f"tested full-range handling with decoders: {sorted_nicely(tested)}")
        if skipped:
            print(f"skipped (unavailable at runtime): {sorted_nicely(skipped)}")
        if not tested:
            self.skipTest("no video decoder able to decode the sample data")

    def _find_sample(self, dec_mod, encoding: str, cs: str):
        data = TEST_COMPRESSED_DATA.get(encoding, {}).get(cs, {})
        if not data:
            return None, ()
        try:
            min_w, min_h = dec_mod.get_min_size(encoding)
        except Exception:
            min_w, min_h = 0, 0
        for size in sorted(data.keys()):
            w, h = size
            if w >= min_w and h >= min_h:
                return size, data[size]
        return None, ()

    def _decode(self, dec_mod, dec_name, encoding: str, cs: str, size, frames, full_range: bool, skipped: list):
        w, h = size
        decoder = None
        try:
            decoder = dec_mod.Decoder()
            decoder.init_context(encoding, w, h, cs, typedict())
            image = None
            for data, frame_options in frames:
                options = typedict(dict(frame_options))
                options["full-range"] = full_range
                image = decoder.decompress_image(data, options)
            if image is None:
                skipped.append(f"{dec_name}:{encoding}:{cs} (no image)")
            return image
        except Exception as e:
            # hardware decoders may not be usable on this host:
            skipped.append(f"{dec_name}:{encoding}:{cs} ({e})")
            return None
        finally:
            if decoder:
                decoder.clean()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
