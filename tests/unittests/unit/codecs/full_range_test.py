#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.codecs.constants import ColorRange

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

# All our compressed sample streams are encoded studio-range:
SAMPLE_FULL_RANGE = False

# Codecs which do not signal the colour range at all
# (there is nothing to verify and exercising them here is slow/flaky):
NO_RANGE_CODECS = ("enc_gstreamer", "dec_gstreamer")

# (encoder, encoding, input colorspace, decoder, output colorspace) combinations
# that carry the colour range through the bitstream from end to end
# (so the decoder recovers it without being told via the client options):
BITSTREAM_ROUNDTRIPS = (
    ("enc_vpx", "vp9", "YUV420P", "dec_vpx", "YUV420P"),
    ("enc_vpx", "vp9", "YUV420P", "dec_libva", "YUV420P"),
    ("enc_x264", "h264", "YUV420P", "dec_openh264", "YUV420P"),
    ("enc_x264", "h264", "YUV420P", "dec_libva", "YUV420P"),
    ("enc_openh264", "h264", "YUV420P", "dec_openh264", "YUV420P"),
    ("enc_openh264", "h264", "YUV420P", "dec_libva", "YUV420P"),
)

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
    """ verify that the video decoders derive the colour range from the bitstream,
        while letting the "full-range" client option override it """

    def test_option_overrides_bitstream(self):
        # the "full-range" decode option must always win, both ways:
        tested: list[str] = []
        skipped: list[str] = []
        for dec_name, dec_mod in self._decoders():
            decoded_any = False
            for encoding, cs, size, frames in self._samples(dec_mod):
                ok = True
                for full_range in (True, False):
                    image = self._decode(dec_mod, dec_name, encoding, cs, size, frames,
                                         {"full-range": full_range}, skipped)
                    if image is None:
                        ok = False
                        break
                    self.assertEqual(
                        bool(image.get_full_range()), full_range,
                        f"{dec_name}: {encoding} produced full-range={bool(image.get_full_range())}"
                        f" when decoding with the full-range={full_range} option")
                if ok:
                    decoded_any = True
            if decoded_any:
                tested.append(dec_name)
        self._report("option override", tested, skipped)

    def test_bitstream_range_without_option(self):
        # with no override, the range must come from the bitstream;
        # all our sample streams are studio-range:
        tested: list[str] = []
        skipped: list[str] = []
        for dec_name, dec_mod in self._decoders():
            decoded_any = False
            for encoding, cs, size, frames in self._samples(dec_mod):
                image = self._decode(dec_mod, dec_name, encoding, cs, size, frames, {}, skipped)
                if image is None:
                    continue
                decoded_any = True
                self.assertEqual(
                    bool(image.get_full_range()), SAMPLE_FULL_RANGE,
                    f"{dec_name}: {encoding} studio-range sample decoded as"
                    f" full-range={bool(image.get_full_range())} without an override option")
            if decoded_any:
                tested.append(dec_name)
        self._report("bitstream range", tested, skipped)

    def _decoders(self):
        for dec_name in loader.DECODER_VIDEO_CODECS:
            if dec_name in NO_RANGE_CODECS:
                continue
            dec_mod = loader.load_codec(dec_name)
            if dec_mod:
                yield dec_name, dec_mod

    def _samples(self, dec_mod):
        for spec in dec_mod.get_specs():
            encoding = spec.encoding
            cs = spec.input_colorspace
            size, frames = self._find_sample(dec_mod, encoding, cs)
            if frames:
                yield encoding, cs, size, frames

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

    def _decode(self, dec_mod, dec_name, encoding: str, cs: str, size, frames, extra_options: dict, skipped: list):
        w, h = size
        decoder = None
        try:
            decoder = dec_mod.Decoder()
            decoder.init_context(encoding, w, h, cs, typedict())
            image = None
            for data, frame_options in frames:
                options = typedict(dict(frame_options))
                options.update(extra_options)
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

    def _report(self, what: str, tested, skipped) -> None:
        print(f"tested {what} with decoders: {sorted_nicely(tested)}")
        if skipped:
            print(f"skipped (unavailable at runtime): {sorted_nicely(skipped)}")
        if not tested:
            self.skipTest("no video decoder able to decode the sample data")


class FullRangeRoundtripTest(unittest.TestCase):
    """ verify the colour range survives a real encode -> decode round-trip
        through the bitstream alone (no "full-range" option on the decode side) """

    def test_bitstream_roundtrip(self):
        tested: list[str] = []
        skipped: list[str] = []
        for enc_name, encoding, in_cs, dec_name, out_cs in BITSTREAM_ROUNDTRIPS:
            enc_mod = loader.load_codec(enc_name)
            dec_mod = loader.load_codec(dec_name)
            if not enc_mod or not dec_mod:
                continue
            spec = self._find_spec(enc_mod, encoding, in_cs, out_cs)
            if not spec:
                continue
            if self._roundtrip(spec, encoding, in_cs, dec_mod, out_cs, skipped):
                tested.append(f"{enc_name}->{dec_name}:{encoding}")
        print(f"tested bitstream colour-range round-trip: {sorted_nicely(tested)}")
        if skipped:
            print(f"skipped (unavailable at runtime): {sorted_nicely(skipped)}")
        if not tested:
            self.skipTest("no encoder/decoder pair able to round-trip the range via the bitstream")

    def _find_spec(self, enc_mod, encoding, in_cs, out_cs):
        for spec in enc_mod.get_specs():
            if spec.encoding == encoding and spec.input_colorspace == in_cs and out_cs in spec.output_colorspaces:
                return spec
        return None

    def _roundtrip(self, spec, encoding, in_cs, dec_mod, out_cs, skipped) -> bool:
        w, h = TEST_SIZE
        label = f"{spec.codec_type}->{dec_mod.get_type()}:{encoding}"
        ok = False
        for full_range in (True, False):
            datas = self._encode(spec, encoding, in_cs, full_range, skipped, label)
            if not datas:
                return ok
            decoded = self._decode_no_option(dec_mod, encoding, out_cs, w, h, datas, skipped, label)
            if decoded is None:
                return ok
            self.assertEqual(
                bool(decoded.get_full_range()), full_range,
                f"{label}: encoded full-range={full_range} but the bitstream decoded as"
                f" {bool(decoded.get_full_range())}")
            ok = True
        return ok

    def _encode(self, spec, encoding, in_cs, full_range, skipped, label):
        w, h = TEST_SIZE
        encoder = spec.codec_class()
        try:
            encoder.init_context(encoding, w, h, in_cs, typedict({
                "full-range": full_range,
                "dst-formats": list(spec.output_colorspaces),
                "quality": 50,
                "speed": 50,
            }))
            datas = []
            for _ in range(3):  # ensure we have a decodable keyframe
                image = make_test_image(in_cs, w, h)
                image.set_full_range(full_range)
                out = encoder.compress_image(image, typedict())
                if out and out[0]:
                    datas.append(out[0])
            return datas
        except Exception as e:
            skipped.append(f"{label} (encode: {e})")
            return []
        finally:
            encoder.clean()

    def _decode_no_option(self, dec_mod, encoding, out_cs, w, h, datas, skipped, label):
        decoder = dec_mod.Decoder()
        try:
            decoder.init_context(encoding, w, h, out_cs, typedict())
            decoded = None
            for data in datas:
                # deliberately pass no "full-range" option: the range must come from the bitstream
                decoded = decoder.decompress_image(data, typedict())
            if decoded is None:
                skipped.append(f"{label} (no image)")
            return decoded
        except Exception as e:
            skipped.append(f"{label} (decode: {e})")
            return None
        finally:
            decoder.clean()


class H264FullRangeParserTest(unittest.TestCase):
    """ verify the standalone H.264 SPS parser recovers video_full_range_flag """

    def test_parses_encoder_sps(self):
        from xpra.codecs.h264_util import get_video_full_range
        w, h = TEST_SIZE
        tested: list[str] = []
        for enc_name in ("enc_x264", "enc_openh264"):
            enc_mod = loader.load_codec(enc_name)
            if not enc_mod:
                continue
            for full_range in (True, False):
                encoder = enc_mod.Encoder()
                encoder.init_context("h264", w, h, "YUV420P",
                                     typedict({"full-range": full_range, "dst-formats": ["YUV420P"]}))
                image = make_test_image("YUV420P", w, h)
                image.set_full_range(full_range)
                data = encoder.compress_image(image, typedict())[0]
                encoder.clean()
                self.assertEqual(
                    get_video_full_range(data), full_range,
                    f"{enc_name}: SPS parsed range does not match encoded full-range={full_range}")
            tested.append(enc_name)
        print(f"tested H.264 SPS parsing with: {sorted_nicely(tested)}")
        if not tested:
            self.skipTest("no H.264 encoder available")

    def test_no_sps_returns_unknown(self):
        from xpra.codecs.h264_util import get_video_full_range
        # empty input, and a stream with only a (non-SPS) coded-slice NAL:
        self.assertEqual(get_video_full_range(b""), ColorRange.UNKNOWN)
        self.assertEqual(get_video_full_range(b"\x00\x00\x01\x41\x9a\x00"), ColorRange.UNKNOWN)


class FirstFrameOnlyTest(unittest.TestCase):
    """ with BACKWARDS_COMPATIBLE off, the colour range is sent in the client options
        of the first frame only (the decoder recovers it from the bitstream afterwards) """

    def test_encoder_sends_range_once(self):
        w, h = TEST_SIZE
        tested: list[str] = []
        for enc_name, encoding, in_cs in (
            ("enc_x264", "h264", "YUV420P"),
            ("enc_openh264", "h264", "YUV420P"),
            ("enc_vpx", "vp9", "YUV420P"),
        ):
            enc_mod = loader.load_codec(enc_name)
            if not enc_mod:
                continue
            spec = None
            for s in enc_mod.get_specs():
                if s.encoding == encoding and s.input_colorspace == in_cs:
                    spec = s
                    break
            if not spec:
                continue
            # the encoders read BACKWARDS_COMPATIBLE from their own module namespace:
            saved = enc_mod.BACKWARDS_COMPATIBLE
            enc_mod.BACKWARDS_COMPATIBLE = False
            try:
                encoder = spec.codec_class()
                encoder.init_context(encoding, w, h, in_cs,
                                     typedict({"full-range": True, "dst-formats": list(spec.output_colorspaces)}))
                frames = 0
                with_flag = 0
                for _ in range(5):
                    image = make_test_image(in_cs, w, h)
                    image.set_full_range(True)
                    out = encoder.compress_image(image, typedict())
                    if not out:
                        continue
                    frames += 1
                    if "full-range" in out[1]:
                        with_flag += 1
                encoder.clean()
            finally:
                enc_mod.BACKWARDS_COMPATIBLE = saved
            self.assertGreaterEqual(frames, 2, f"{enc_name}: need at least 2 frames to test")
            self.assertEqual(
                with_flag, 1,
                f"{enc_name}: with BACKWARDS_COMPATIBLE off, 'full-range' should appear in exactly"
                f" one frame's client options, but it appeared in {with_flag} of {frames}")
            tested.append(enc_name)
        print(f"tested first-frame-only signalling with: {sorted_nicely(tested)}")
        if not tested:
            self.skipTest("no encoder available")


class OptionMemoryRoundtripTest(unittest.TestCase):
    """ with BACKWARDS_COMPATIBLE off the colour range is only signalled on the first frame;
        the decoder must remember it for the following frames. This is essential for vp8,
        which has no colour-range syntax in its bitstream at all. """

    # (encoder, encoding, input cs, decoder, output cs):
    COMBOS = (
        ("enc_vpx", "vp8", "YUV420P", "dec_vpx", "YUV420P"),
        ("enc_vpx", "vp9", "YUV420P", "dec_vpx", "YUV420P"),
        ("enc_x264", "h264", "YUV420P", "dec_openh264", "YUV420P"),
        ("enc_openh264", "h264", "YUV420P", "dec_openh264", "YUV420P"),
        # libva also has no vp8 range syntax, so it must remember the range too:
        ("enc_vpx", "vp8", "YUV420P", "dec_libva", "YUV420P"),
        ("enc_vpx", "vp9", "YUV420P", "dec_libva", "YUV420P"),
        ("enc_x264", "h264", "YUV420P", "dec_libva", "YUV420P"),
    )

    def test_decoder_remembers_range(self):
        tested: list[str] = []
        skipped: list[str] = []
        for enc_name, encoding, in_cs, dec_name, out_cs in self.COMBOS:
            enc_mod = loader.load_codec(enc_name)
            dec_mod = loader.load_codec(dec_name)
            if not enc_mod or not dec_mod:
                continue
            spec = None
            for s in enc_mod.get_specs():
                if s.encoding == encoding and s.input_colorspace == in_cs and out_cs in s.output_colorspaces:
                    spec = s
                    break
            if not spec:
                continue
            if self._check(enc_mod, dec_mod, spec, encoding, in_cs, out_cs, skipped):
                tested.append(f"{enc_name}->{dec_name}:{encoding}")
        print(f"tested first-frame-only option memory: {sorted_nicely(tested)}")
        if skipped:
            print(f"skipped (unavailable at runtime): {sorted_nicely(skipped)}")
        if not tested:
            self.skipTest("no encoder/decoder pair available")

    def _check(self, enc_mod, dec_mod, spec, encoding, in_cs, out_cs, skipped) -> bool:
        w, h = TEST_SIZE
        label = f"{spec.codec_type}->{dec_mod.get_type()}:{encoding}"
        ok = False
        for full_range in (True, False):
            saved = enc_mod.BACKWARDS_COMPATIBLE
            enc_mod.BACKWARDS_COMPATIBLE = False
            try:
                frames = self._encode(spec, encoding, in_cs, full_range)
            except Exception as e:
                skipped.append(f"{label} (encode: {e})")
                return ok
            finally:
                enc_mod.BACKWARDS_COMPATIBLE = saved
            if len(frames) < 2:
                skipped.append(f"{label} (only {len(frames)} frame(s))")
                return ok
            # with BACKWARDS_COMPATIBLE off, the option is sent on the first frame only:
            self.assertIn("full-range", frames[0][1],
                          f"{label}: the first frame should carry the 'full-range' option")
            self.assertNotIn("full-range", frames[-1][1],
                             f"{label}: later frames should not repeat the 'full-range' option")
            decoder = dec_mod.Decoder()
            try:
                decoder.init_context(encoding, w, h, out_cs, typedict())
                for i, (data, copts) in enumerate(frames):
                    decoded = decoder.decompress_image(data, typedict(copts))
                    if decoded is None:
                        continue
                    self.assertEqual(
                        bool(decoded.get_full_range()), full_range,
                        f"{label}: frame {i} (carried option: {'full-range' in copts}) decoded as"
                        f" full_range={bool(decoded.get_full_range())} but expected {full_range}")
            except Exception as e:
                skipped.append(f"{label} (decode: {e})")
                return ok
            finally:
                decoder.clean()
            ok = True
        return ok

    def _encode(self, spec, encoding, in_cs, full_range):
        w, h = TEST_SIZE
        encoder = spec.codec_class()
        frames = []
        try:
            encoder.init_context(encoding, w, h, in_cs, typedict({
                "full-range": full_range,
                "dst-formats": list(spec.output_colorspaces),
                "quality": 50,
                "speed": 50,
            }))
            for _ in range(4):
                image = make_test_image(in_cs, w, h)
                image.set_full_range(full_range)
                data, copts = encoder.compress_image(image, typedict())
                if data:
                    frames.append((data, copts))
        finally:
            encoder.clean()
        return frames


def main():
    unittest.main()


if __name__ == '__main__':
    main()
