#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.codecs import checks
from xpra.codecs.constants import EncodingNotSupported


class DecoderModule:

    def __init__(self, encodings):
        self.encodings = tuple(encodings)

    @staticmethod
    def get_type():
        return "test"

    def get_encodings(self):
        return self.encodings

    def get_specs(self):
        return tuple(SimpleNamespace(encoding=encoding, input_colorspace="YUV420P")
                     for encoding in self.encodings)


class CodecChecksTest(unittest.TestCase):

    def test_unsupported_decoder_probes_are_only_logged_as_debug(self):
        decoder_module = DecoderModule(("h264", "vp8", "vp9"))
        with patch.object(checks, "testdecoding", side_effect=EncodingNotSupported("unsupported")), \
                patch.object(checks, "log") as log:
            self.assertEqual(checks.testdecoder(decoder_module, False), ())

        self.assertEqual(log.call_count, 3)
        for encoding in decoder_module.get_encodings():
            log.assert_any_call(f"test: {encoding} decoding failed", exc_info=True)
        log.warn.assert_called_once_with("Warning: all the test decoders have failed! (h264, vp8, vp9)")
        log.error.assert_not_called()

    def test_other_decoder_probe_failures_still_warn(self):
        decoder_module = DecoderModule(("h264", "vp9"))

        def testdecoding(_decoder_module, encoding, _colorspace, _full):
            if encoding == "h264":
                raise RuntimeError("probe failed")

        with patch.object(checks, "testdecoding", side_effect=testdecoding), \
                patch.object(checks, "log") as log:
            self.assertEqual(checks.testdecoder(decoder_module, False), ("vp9",))

        log.warn.assert_called_once_with("test: h264 decoding failed: probe failed")
        log.error.assert_not_called()

    def test_unsupported_frame_is_not_logged_as_an_error(self):
        class Decoder:

            @staticmethod
            def init_context(*_args):
                pass

            @staticmethod
            def decompress_image(*_args):
                raise EncodingNotSupported("unsupported")

            @staticmethod
            def clean():
                pass

        decoder_module = SimpleNamespace(
            Decoder=Decoder,
            get_min_size=lambda _encoding: (1, 1),
            get_type=lambda: "test",
        )
        test_data = {
            "test": {
                "YUV420P": {
                    (2, 2): ((b"data", {}), ),
                },
            },
        }
        with patch.dict(checks.TEST_COMPRESSED_DATA, test_data), \
                patch.object(checks, "log") as log, \
                self.assertRaises(EncodingNotSupported):
            checks.testdecoding(decoder_module, "test", "YUV420P", False)

        log.error.assert_not_called()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
