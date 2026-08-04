#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.colourspace import (
    Colourspace, SRGB,
    Primaries, TransferFunction, MatrixCoefficients, Range,
)


class TestColourspace(unittest.TestCase):

    def test_srgb_defaults(self):
        self.assertEqual(SRGB.primaries, Primaries.BT709)
        self.assertEqual(SRGB.transfer, TransferFunction.SRGB)
        self.assertEqual(SRGB.matrix, MatrixCoefficients.IDENTITY)
        self.assertEqual(SRGB.range, Range.FULL)

    def test_to_dict(self):
        d = SRGB.to_dict()
        self.assertEqual(d, {"primaries": 1, "transfer": 13, "matrix": 0, "range": 1})
        # the values must be plain integers so they can be sent as capabilities:
        for v in d.values():
            self.assertEqual(type(v), int)

    def test_round_trip(self):
        for cs in (
            SRGB,
            Colourspace(primaries=Primaries.BT2020, transfer=TransferFunction.PQ,
                        matrix=MatrixCoefficients.BT2020_NCL, range=Range.LIMITED),
            Colourspace(primaries=Primaries.DISPLAY_P3, transfer=TransferFunction.LINEAR,
                        matrix=MatrixCoefficients.IDENTITY, range=Range.FULL),
        ):
            self.assertEqual(Colourspace.from_dict(cs.to_dict()), cs)

    def test_from_dict_invalid(self):
        # anything we cannot make sense of must fall back to sRGB:
        for value in (None, {}, "", 0, [], (), {"primaries": "invalid"}, {"transfer": None},
                      {"primaries": 999, "transfer": 999, "matrix": 999, "range": 999}):
            self.assertEqual(Colourspace.from_dict(value), SRGB, f"for {value!r}")

    def test_from_dict_partial(self):
        # unknown values must not discard the ones we can parse:
        cs = Colourspace.from_dict({"primaries": int(Primaries.BT2020), "transfer": 999})
        self.assertEqual(cs.primaries, Primaries.BT2020)
        self.assertEqual(cs.transfer, SRGB.transfer)
        self.assertEqual(cs.matrix, SRGB.matrix)

    def test_from_dict_default(self):
        default = Colourspace(primaries=Primaries.BT2020, transfer=TransferFunction.PQ,
                              matrix=MatrixCoefficients.BT2020_NCL, range=Range.LIMITED)
        self.assertEqual(Colourspace.from_dict(None, default), default)
        self.assertEqual(Colourspace.from_dict({}, default), default)

    def test_str(self):
        s = str(SRGB)
        self.assertIn("BT709", s)
        self.assertIn("SRGB", s)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
