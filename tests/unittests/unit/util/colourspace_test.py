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
        # names, not H.273 numbers: the wire and `xpra info` have to be readable.
        # (this pins the wire format: renaming an enum member would change it)
        self.assertEqual(d, {"primaries": "bt709", "transfer": "srgb", "matrix": "identity", "range": "full"})
        for v in d.values():
            self.assertEqual(type(v), str)

    def test_wire_names(self):
        from xpra.util.colourspace import wire_name
        self.assertEqual(wire_name(Primaries.DISPLAY_P3), "display-p3")
        self.assertEqual(wire_name(MatrixCoefficients.BT2020_NCL), "bt2020-ncl")
        self.assertEqual(wire_name(TransferFunction.IEC61966_2_4), "iec61966-2-4")
        # every attribute must have a distinct name within its own enum,
        # otherwise `from_dict` could not tell them apart:
        for enum_class in (Primaries, TransferFunction, MatrixCoefficients, Range):
            names = [wire_name(v) for v in enum_class]
            self.assertEqual(len(names), len(set(names)), f"duplicate wire names in {enum_class}")

    def test_h273_values(self):
        # the values stay H.273 code points, so they can be given to the encoders as-is:
        self.assertEqual(int(Primaries.BT2020), 9)
        self.assertEqual(int(TransferFunction.PQ), 16)
        self.assertEqual(int(MatrixCoefficients.IDENTITY), 0)

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
        # anything we cannot make sense of must fall back to sRGB,
        # including the H.273 numbers themselves: those are not a wire format
        for value in (None, {}, "", 0, [], (), {"primaries": "invalid"}, {"transfer": None},
                      {"primaries": 9, "transfer": 16, "matrix": 0, "range": 0},
                      {"primaries": "nope", "transfer": "nope", "matrix": "nope", "range": "nope"}):
            self.assertEqual(Colourspace.from_dict(value), SRGB, f"for {value!r}")

    def test_from_dict_bytes(self):
        # some packet encoders hand us bytes rather than strings:
        self.assertEqual(Colourspace.from_dict({"primaries": b"bt2020"}).primaries, Primaries.BT2020)

    def test_from_dict_partial(self):
        # unknown values must not discard the ones we can parse:
        cs = Colourspace.from_dict({"primaries": "bt2020", "transfer": "nope"})
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


P3 = Colourspace(primaries=Primaries.DISPLAY_P3, transfer=TransferFunction.SRGB,
                 matrix=MatrixCoefficients.IDENTITY, range=Range.FULL)
REC2020 = Colourspace(primaries=Primaries.BT2020, transfer=TransferFunction.PQ,
                      matrix=MatrixCoefficients.BT2020_NCL, range=Range.LIMITED)


class FakeDisplay:
    def __init__(self, colourspace):
        self.server_colourspace = colourspace


class FakeClient:
    def __init__(self, display):
        self.display = display

    def get_subsystem(self, name):
        return self.display if name == "display" else None


class FakeWindow:
    # borrow the real resolution logic without constructing a real window:
    from xpra.client.gui.window_base import ClientWindowBase
    get_session_colourspace = ClientWindowBase.get_session_colourspace
    get_colourspace = ClientWindowBase.get_colourspace
    del ClientWindowBase

    def __init__(self, client, colourspace=None):
        self._client = client
        self.colourspace = colourspace


class TestColourspaceResolution(unittest.TestCase):
    """ the client resolves: window metadata -> session -> sRGB """

    def test_untagged_window_uses_the_session(self):
        win = FakeWindow(FakeClient(FakeDisplay(P3)))
        self.assertEqual(win.get_colourspace(), P3)

    def test_tagged_window_wins(self):
        win = FakeWindow(FakeClient(FakeDisplay(P3)), REC2020)
        self.assertEqual(win.get_colourspace(), REC2020)

    def test_no_display_subsystem(self):
        win = FakeWindow(FakeClient(None))
        self.assertEqual(win.get_colourspace(), SRGB)

    def test_display_without_colourspace(self):
        # ie: a client subsystem from before the capability existed
        class Bare:
            pass
        win = FakeWindow(FakeClient(Bare()))
        self.assertEqual(win.get_colourspace(), SRGB)


class TestColourspaceMetadata(unittest.TestCase):

    def test_window_metadata_default(self):
        from xpra.server.window.metadata import DEFAULT_VALUES
        # windows are in the session colourspace unless the model says otherwise,
        # so the default has to match what an untagged window resolves to:
        self.assertEqual(DEFAULT_VALUES["colourspace"], SRGB.to_dict())

    def test_metadata_is_supported(self):
        from xpra.constants import DEFAULT_METADATA_SUPPORTED
        self.assertIn("colourspace", DEFAULT_METADATA_SUPPORTED)

    def test_monitor_data(self):
        from xpra.util.parsing import validated_monitor_data
        mon = validated_monitor_data({0: {"geometry": (0, 0, 1024, 768), "colourspace": P3.to_dict()}})
        self.assertEqual(Colourspace.from_dict(mon[0]["colourspace"]), P3)


class TestWaylandColourspace(unittest.TestCase):
    """ `wp_color_manager_v1` named enums -> H.273 code points """

    def setUp(self):
        # the mapping tables are pure python (no wayland or wlroots needed to exercise them),
        # but the package they live in is only installed when the wayland backend is built:
        try:
            from xpra.wayland.server.colourspace import get_colourspace, PRIMARIES, TRANSFER_FUNCTIONS
        except ImportError:
            raise unittest.SkipTest("the wayland server backend is not installed") from None
        self.get_colourspace = get_colourspace
        self.PRIMARIES = PRIMARIES
        self.TRANSFER_FUNCTIONS = TRANSFER_FUNCTIONS

    def test_untagged_is_srgb(self):
        # zero means "unset" for both values:
        self.assertEqual(self.get_colourspace(0, 0), SRGB)

    def test_srgb(self):
        # wp `primaries.srgb` = 1, `transfer_function.srgb` = 9
        self.assertEqual(self.get_colourspace(1, 9), SRGB)

    def test_hdr10(self):
        # wp `primaries.bt2020` = 6, `transfer_function.st2084_pq` = 11
        cs = self.get_colourspace(6, 11)
        self.assertEqual(cs.primaries, Primaries.BT2020)
        self.assertEqual(cs.transfer, TransferFunction.PQ)
        # wayland surfaces are always RGB and full range:
        self.assertEqual(cs.matrix, MatrixCoefficients.IDENTITY)
        self.assertEqual(cs.range, Range.FULL)

    def test_display_p3(self):
        # wp `primaries.display_p3` = 9
        self.assertEqual(self.get_colourspace(9, 9), P3)

    def test_partial_tag(self):
        # a surface may name only one of the two, the other keeps its sRGB value:
        self.assertEqual(self.get_colourspace(6, 0).transfer, SRGB.transfer)
        self.assertEqual(self.get_colourspace(0, 11).primaries, SRGB.primaries)

    def test_unknown_values_fall_back(self):
        # ie: `adobe_rgb` (10), which has no H.273 code point, or a newer enum value:
        self.assertEqual(self.get_colourspace(10, 99), SRGB)

    def test_tables_are_valid_code_points(self):
        # guards against a typo turning into a bogus code point on the wire:
        for value in self.PRIMARIES.values():
            self.assertIsInstance(value, Primaries)
        for value in self.TRANSFER_FUNCTIONS.values():
            self.assertIsInstance(value, TransferFunction)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
