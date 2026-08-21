#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

try:
    from xpra.client.terminal import input as terminal_input
    from xpra.client.terminal import keys as terminal_keys
except ImportError:
    terminal_input = None
    terminal_keys = None


# every shape of SGR report we can receive, used for the split point tests:
CORPUS = (
    b"\x1b[<0;1;2M", b"\x1b[<0;1;2m",
    b"\x1b[<1;100;200M", b"\x1b[<2;100;200m",
    b"\x1b[<32;3;4M", b"\x1b[<35;5;6M",
    b"\x1b[<64;7;8M", b"\x1b[<65;7;8M", b"\x1b[<66;7;8M", b"\x1b[<67;7;8M",
    b"\x1b[<4;9;10M", b"\x1b[<8;9;10M", b"\x1b[<16;9;10M", b"\x1b[<28;9;10M",
    b"\x1b[<128;11;12M", b"\x1b[<131;11;12m",
    b"\x1b[<1023;1920;1080M",
)


@unittest.skipIf(terminal_input is None, "the terminal client component is not built")
class SGRMouseTest(unittest.TestCase):

    def parse(self, data: bytes) -> list:
        return terminal_input.InputParser().feed(data)

    def one(self, data: bytes):
        events = self.parse(data)
        self.assertEqual(len(events), 1, f"expected a single event from {data!r}, got {events}")
        event = events[0]
        self.assertIsInstance(event, terminal_input.MouseEvent)
        return event

    def test_press_and_release(self):
        for code, button in ((0, 1), (1, 2), (2, 3)):
            event = self.one(b"\x1b[<%i;100;200M" % code)
            self.assertEqual((event.x, event.y), (100, 200))
            self.assertEqual(event.button, button)
            self.assertEqual(event.event, "press")
            self.assertEqual(event.mods, 0)
            event = self.one(b"\x1b[<%i;100;200m" % code)
            self.assertEqual(event.button, button)
            self.assertEqual(event.event, "release")

    def test_pixel_coordinates(self):
        # mode 1016 reports pixels, so the values are not limited to the cell grid:
        event = self.one(b"\x1b[<0;1920;1080M")
        self.assertEqual((event.x, event.y), (1920, 1080))
        event = self.one(b"\x1b[<0;1;1M")
        self.assertEqual((event.x, event.y), (1, 1))

    def test_motion(self):
        # bit 32 with a button held is a drag:
        for code, button in ((32, 1), (33, 2), (34, 3)):
            event = self.one(b"\x1b[<%i;10;20M" % code)
            self.assertEqual(event.event, "motion")
            self.assertEqual(event.button, button)
            self.assertEqual((event.x, event.y), (10, 20))
        # 3 means "no button":
        event = self.one(b"\x1b[<35;10;20M")
        self.assertEqual(event.event, "motion")
        self.assertEqual(event.button, 0)

    def test_wheel(self):
        for code, button in ((64, 4), (65, 5), (66, 6), (67, 7)):
            event = self.one(b"\x1b[<%i;5;6M" % code)
            self.assertEqual(event.event, "wheel")
            self.assertEqual(event.button, button)
            self.assertEqual((event.x, event.y), (5, 6))
            self.assertEqual(event.mods, 0)

    def test_extra_buttons(self):
        for code, button in ((128, 8), (129, 9), (130, 10), (131, 11)):
            event = self.one(b"\x1b[<%i;1;2M" % code)
            self.assertEqual(event.button, button)
            self.assertEqual(event.event, "press")
            event = self.one(b"\x1b[<%i;1;2m" % code)
            self.assertEqual(event.button, button)
            self.assertEqual(event.event, "release")

    def test_modifiers(self):
        # SGR bits 4/8/16 are shift/alt/ctrl, reported as the kitty modifier bits:
        expected = {
            4: terminal_input.MOD_SHIFT,
            8: terminal_input.MOD_ALT,
            16: terminal_input.MOD_CTRL,
            4 | 8: terminal_input.MOD_SHIFT | terminal_input.MOD_ALT,
            4 | 8 | 16: terminal_input.MOD_SHIFT | terminal_input.MOD_ALT | terminal_input.MOD_CTRL,
        }
        for code, mods in expected.items():
            event = self.one(b"\x1b[<%i;1;2M" % code)
            self.assertEqual(event.mods, mods, f"wrong modifiers for SGR button {code}")
            self.assertEqual(event.button, 1)
            self.assertEqual(event.event, "press")
        # modifiers on a wheel event:
        event = self.one(b"\x1b[<%i;1;2M" % (64 | 16))
        self.assertEqual(event.event, "wheel")
        self.assertEqual(event.button, 4)
        self.assertEqual(event.mods, terminal_input.MOD_CTRL)
        # modifiers on a drag:
        event = self.one(b"\x1b[<%i;1;2M" % (32 | 4))
        self.assertEqual(event.event, "motion")
        self.assertEqual(event.button, 1)
        self.assertEqual(event.mods, terminal_input.MOD_SHIFT)

    @unittest.skipIf(terminal_keys is None, "the terminal client component is not built")
    def test_modifier_names(self):
        event = self.one(b"\x1b[<%i;1;2M" % (4 | 16))
        self.assertEqual(terminal_keys.modifier_names(event.mods), ["shift", "control"])
        event = self.one(b"\x1b[<%i;1;2M" % 8)
        self.assertEqual(terminal_keys.modifier_names(event.mods), ["mod1"])

    def test_truncated(self):
        parser = terminal_input.InputParser()
        for chunk in (b"\x1b", b"[", b"<", b"0;", b"100", b";20"):
            self.assertEqual(parser.feed(chunk), [], f"{chunk!r} should not complete the report")
        events = parser.feed(b"0M")
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0].x, events[0].y), (100, 200))
        self.assertEqual(events[0].event, "press")

    def test_malformed(self):
        # not enough parameters, too many, non numeric, or an unknown final byte:
        for data in (b"\x1b[<M", b"\x1b[<0M", b"\x1b[<0;1M", b"\x1b[<0;1;2;3M",
                     b"\x1b[<;;M", b"\x1b[<0;1;M", b"\x1b[<:;1;2M", b"\x1b[<0;1;2X", b"\x1b[<0;1;2H"):
            self.assertEqual(self.parse(data), [], f"{data!r} should not produce an event")

    def test_malformed_does_not_swallow(self):
        events = self.parse(b"\x1b[<0;1M\x1b[<0;10;20M")
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0].x, events[0].y), (10, 20))
        # an aborted report followed by a valid one:
        events = self.parse(b"\x1b[<0;1\x1b[<1;10;20m")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].button, 2)
        self.assertEqual(events[0].event, "release")
        # a byte that cannot appear in the parameter area ends the sequence there,
        # everything after it is re-parsed from scratch rather than discarded:
        events = self.parse(b"\x1b[<abcM")
        self.assertEqual([event.code for event in events], [98, 99, 77])

    def test_mixed_with_keys(self):
        events = self.parse(b"a\x1b[<0;10;20Mb")
        self.assertEqual(len(events), 3)
        self.assertIsInstance(events[0], terminal_input.KeyEvent)
        self.assertIsInstance(events[1], terminal_input.MouseEvent)
        self.assertIsInstance(events[2], terminal_input.KeyEvent)
        self.assertEqual(events[0].code, 97)
        self.assertEqual(events[2].code, 98)

    def test_incremental_equivalence(self):
        data = b"".join(CORPUS)
        whole = terminal_input.InputParser().feed(data)
        self.assertEqual(len(whole), len(CORPUS))
        parser = terminal_input.InputParser()
        one_at_a_time = []
        for i in range(len(data)):
            one_at_a_time += parser.feed(data[i:i + 1])
        self.assertEqual(whole, one_at_a_time)

    def test_every_split_point(self):
        data = b"".join(CORPUS)
        whole = terminal_input.InputParser().feed(data)
        for split in range(len(data) + 1):
            parser = terminal_input.InputParser()
            events = parser.feed(data[:split])
            events += parser.feed(data[split:])
            self.assertEqual(events, whole, f"mismatch when splitting at {split}")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
