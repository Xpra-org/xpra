#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import typedict
from xpra.util.str_fn import hexstr, memoryview_to_bytes, repr_ellipsized
from xpra.codecs import loader
from xpra.codecs.checks import make_test_image, h2b


def cmpp(p1, p2) -> int:
    # compare planes, tolerate a rounding difference of 1
    size = min(len(p1), len(p2))
    delta = 0
    for i in range(size):
        v1 = p1[i]
        v2 = p2[i]
        delta = max(delta, abs(v2 - v1))
    return delta


def cmpe(info: str, p1, p2, tolerance=2):
    delta = cmpp(p1, p2)
    if delta > tolerance:
        raise ValueError(f"{info} delta={delta}")


def mod_check(mod_name: str, in_csc: str, out_csc: str):
    csc_mod = loader.load_codec(mod_name)
    if not csc_mod:
        raise ValueError(f"{mod_name} not found")
    specs = csc_mod.get_specs()
    in_match = tuple(spec for spec in specs if spec.input_colorspace == in_csc)
    if not in_match:
        raise ValueError(f"{mod_name} does not support {in_csc!r} as input for {out_csc!r}")
    out_match = tuple(spec for spec in specs if out_csc not in spec.output_colorspaces)
    if not out_match:
        raise ValueError(f"{mod_name} does not support {out_csc!r} as output for {in_csc!r}")
    return csc_mod


def pstr(pixel_data) -> str:
    bdata = memoryview_to_bytes(pixel_data)
    return repr_ellipsized(hexstr(bdata))


CS_TEST_DATA = {
    "full": (
        ("black", "000000ff", "00", "80", "80"),
        ("white", "ffffffff", "ff", "80", "80"),
        ("green", "00ff00ff", "95", "2c", "15"),
        ("red", "ff0000ff", "1d", "ff", "6b"),
        ("blue", "0000ffff", "4d", "55", "ff"),
        ("cyan", "00ffffff", "e2", "00", "94"),
        ("magenta", "ff00ffff", "6a", "d4", "eb"),
        ("yellow", "ffff00ff", "b2", "ab", "01"),
    ),
    "studio": {
        ("black", "000000ff", "10", "80", "80"),
        ("white", "ffffffff", "eb", "80", "80"),
        ("green", "00ff00ff", "90", "36", "22"),
        ("red", "ff0000ff", "29", "ef", "6e"),
        ("blue", "0000ffff", "52", "5a", "ef"),
        ("cyan", "00ffffff", "d2", "10", "91"),
        ("magenta", "ff00ffff", "6a", "c9", "dd"),
        ("yellow", "ffff00ff", "a9", "a5", "10"),
        ("beige", "f5f5dcff", "dc", "83", "75"),
        ("orange", "ffa500ff", "7c", "bf", "31"),
        ("brown", "a52a2aff", "40", "b5", "77"),
    },
}


class Test_CSC_Colorspace(unittest.TestCase):

    def _do_test_RGB_to_YUV(self, mod_out: str, mod_in: str,
                            width=16, height=16,
                            color_name="",
                            in_csc="BGRX", out_csc="YUV420P",
                            pixel="00000000", expected=(),
                            options=typedict()) -> None:
        csc_mod = mod_check(mod_out, in_csc, out_csc)
        csc_out = csc_mod.Converter()
        csc_out.init_context(width, height, in_csc,
                             width, height, out_csc, options)
        in_image = make_test_image(in_csc, width, height, pixel)
        in_pixels = h2b(pixel) * width * height
        out_image = csc_out.convert_image(in_image)
        csc_out.clean()
        assert out_image.get_planes() >= len(expected)
        info = f"{in_csc} to {out_csc} {color_name!r} {options}"
        # now verify the value for each plane specified:
        for i, v_str in enumerate(expected):
            plane = out_image.get_pixels()[i]
            # plane_stride = out_image.get_rowstride()[i]
            # assert len(plane)>=plane_stride*out_image.get_height()
            plane_bytes = memoryview_to_bytes(plane)
            v = h2b(v_str)
            cmpe(f"{mod_out}: {info} plane %s, expected %s but got %s" % (
                out_csc[i], v_str, pstr(plane_bytes[:len(v)])),
                plane_bytes, v)
            # print("%s %s : %s (%i bytes - %s)" % (mod, out_csc[i], hexstr(plane), len(plane), type(plane)))
            # print("%s : %s" % (out_csc[i], hexstr(plane_bytes)))

        # and back again:
        csc_mod = mod_check(mod_in, out_csc, in_csc)
        csc_in = csc_mod.Converter()
        csc_in.init_context(width, height, out_csc,
                            width, height, in_csc, options)
        roundtrip_image = csc_in.convert_image(out_image)
        csc_in.clean()
        roundtrip_pixels = memoryview(roundtrip_image.get_pixels())
        pixel_bytes = memoryview_to_bytes(roundtrip_pixels)
        cmpe(f"roundtrip {mod_out}-{mod_in} {info} mismatch, expected %s but got %s" % (pstr(in_pixels), pstr(pixel_bytes)),
             in_pixels, pixel_bytes, tolerance=2 + 2*int(not options.boolget("full-range")))

    def _test_RGB_to_YUV(self, mod_out, mod_in, in_csc="BGRX", out_csc="YUV420P", cs_range="full"):
        width = height = 32
        test_data = CS_TEST_DATA[cs_range]
        options = typedict({"full-range": cs_range == "full"})
        for color_name, pixel, Y, U, V in test_data:
            self._do_test_RGB_to_YUV(
                mod_out, mod_in,
                width, height,
                color_name,
                in_csc=in_csc, out_csc=out_csc,
                pixel=pixel, expected=(Y * width, U * (width // 2), V * (width // 2)),
                options=options,
            )

    def do_test_RGB_to_YUV(self, mod_out: str, mod_in: str, rgb_format="BGRX") -> None:
        for cs_range in ("studio", "full"):
            for yuv in ("420", "444"):
                if mod_out == "csc_libyuv" and yuv == "444" and cs_range == "full":
                    # not implemented in libyuv!
                    continue
                self._test_RGB_to_YUV(mod_out, mod_in, rgb_format, f"YUV{yuv}P", cs_range)

    def test_BGRX_to_YUV(self):
        modules = loader.CSC_CODECS
        found = []
        for mod in modules:
            if loader.load_codec(mod):
                found.append(mod)
                self.do_test_RGB_to_YUV(mod, mod, "BGRX")
        if len(found) >= 2:
            self.do_test_RGB_to_YUV(found[0], found[1], "BGRX")
            self.do_test_RGB_to_YUV(found[1], found[0], "BGRX")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
