#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.clipboard_packet import (
    FORMAT_SIZES, MAX_CLIPBOARD_TARGETS,
    get_name, get_names, parse_wire_data, parse_clipboard_data_items,
)

MAX_SIZE = 1024


class ClipboardPacketTest(unittest.TestCase):

    def test_names(self):
        for name in ("UTF8_STRING", "text/plain; charset=utf-8", b"TARGETS", "x" * 256):
            self.assertEqual(get_name(name), name.decode() if isinstance(name, bytes) else name)
        for name in ("", "x" * 257, "a\nb", "a\x00b", "café", b"caf\xc3\xa9", 1, None, ("a", )):
            with self.assertRaises(ValueError, msg=f"{name!r} accepted"):
                get_name(name)
        self.assertEqual(get_names(("UTF8_STRING", "", "a\tb", b"TEXT")), ("UTF8_STRING", "TEXT"))
        with self.assertRaises(TypeError):
            get_names("UTF8_STRING")

    def test_wire_data(self):
        self.assertEqual(parse_wire_data("bytes", 8, b"hello", MAX_SIZE), (b"hello", 5))
        self.assertEqual(parse_wire_data("bytes", 8, "hello", MAX_SIZE), (b"hello", 5))
        self.assertEqual(parse_wire_data("integers", 16, [1, 65535], MAX_SIZE), ((1, 65535), 4))
        self.assertEqual(parse_wire_data("integers", 32, (2**32, ), MAX_SIZE)[0], (2**32, ))
        self.assertEqual(parse_wire_data("atoms", 32, ("TARGETS", "a\nb"), MAX_SIZE), (("TARGETS", ), 7))
        for args in (
            ("zlib", 8, b"x"),
            ("bytes", 7, b"x"),
            ("bytes", 8, 1),
            ("bytes", 8, b"x" * (MAX_SIZE + 1)),
            ("integers", 8, b"x"),
            ("integers", 8, (256, )),
            ("integers", 16, (-1, )),
            ("integers", 16, (True, )),
            ("integers", 32, (2 ** (8 * FORMAT_SIZES[32]), )),
            ("integers", 16, (1, ) * (MAX_SIZE // 2 + 1)),
            ("atoms", 32, "TARGETS"),
            ("atoms", 32, ("x" * 200, ) * 6),
        ):
            with self.assertRaises((ValueError, TypeError), msg=f"{args!r} accepted"):
                parse_wire_data(*args, MAX_SIZE)

    def test_data_items(self):
        item = ("STRING", 8, "bytes", b"hello")
        self.assertEqual(parse_clipboard_data_items({"UTF8_STRING": item}, MAX_SIZE), {"UTF8_STRING": item})
        for items in (
            [],
            {"UTF8_STRING": item[:3]},
            {"UTF8_STRING": item + ("extra", )},
            {"": item},
            {"UTF8_STRING": ("", 8, "bytes", b"x")},
            {"UTF8_STRING": ("STRING", "8", "bytes", b"x")},
            {"UTF8_STRING": ("STRING", 8, b"bytes", b"x")},
            {f"text/x-{i}": item for i in range(MAX_CLIPBOARD_TARGETS + 1)},
            # the data of all the targets must fit in the budget:
            {
                "UTF8_STRING": ("STRING", 8, "bytes", b"x" * (MAX_SIZE // 2 + 1)),
                "TEXT": ("STRING", 8, "bytes", b"x" * (MAX_SIZE // 2 + 1)),
            },
        ):
            with self.assertRaises((ValueError, TypeError), msg=f"{items!r} accepted"):
                parse_clipboard_data_items(items, MAX_SIZE)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
