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


# one sample of every kind of event the parser can produce,
# used to verify that the parser survives arbitrary split points:
CORPUS = (
    b"\x1b[97u",                        # kitty: `a`
    b"\x1b[97:65:97;2u",                # kitty: shift+`a` with alternates
    b"\x1b[97;5:3u",                    # kitty: ctrl+`a` release
    b"\x1b[97;1:2;97u",                 # kitty: `a` repeat with associated text
    b"\x1b[57444;9u",                   # kitty: super+Super_L
    b"\x1b[A",                          # legacy Up
    b"\x1b[1;5C",                       # legacy ctrl+Right
    b"\x1b[3~",                         # legacy Delete
    b"\x1b[15;2~",                      # legacy shift+F5
    b"\x1bOQ",                          # SS3 F2
    b"a",                               # printable ascii
    "é".encode(),                  # printable 2 byte utf8
    "☃".encode(),                  # printable 3 byte utf8
    b"\x1ba",                           # alt+`a`
    b"\r", b"\t", b"\x7f", b"\x08",     # Return, Tab, BackSpace, BackSpace
    b"\x03",                            # ctrl+`c`
    b"\x1b[?15u",                       # keyboard flags answer
    b"\x1b_Gi=3;OK\x1b\\",              # graphics answer
    b"\x1b_Gi=7;ENOENT:nope\x1b\\",     # graphics error
    b"\x1b[4;600;800t",                 # text area size report
    b"\x1b[<0;100;200M",                # mouse press
    b"\x1b[<35;10;20M",                 # mouse motion, no button
    b"\x1b[<65;5;6M",                   # wheel down
    b"\x1b]52;c;QUJD\x07",              # an OSC we do not care about
    b"\x1bP1$r0m\x1b\\",                # a DCS we do not care about
    b"\x1b[\x1b[B",                     # an aborted control sequence, then Down
    b"\xff",                            # an invalid utf8 byte
    b"\x1b[999X",                       # an unknown control sequence
    b"Z",                               # printable ascii again
)


@unittest.skipIf(terminal_input is None, "the terminal client component is not built")
class KittyKeyboardParserTest(unittest.TestCase):

    def parse(self, data: bytes) -> list:
        return terminal_input.InputParser().feed(data)

    def one(self, data: bytes):
        events = self.parse(data)
        self.assertEqual(len(events), 1, f"expected a single event from {data!r}, got {events}")
        return events[0]

    def key(self, data: bytes):
        event = self.one(data)
        self.assertIsInstance(event, terminal_input.KeyEvent)
        return event

    def test_csi_u_minimal(self):
        event = self.key(b"\x1b[97u")
        self.assertEqual(event.code, 97)
        self.assertEqual(event.shifted, 0)
        self.assertEqual(event.base, 0)
        self.assertEqual(event.mods, 0)
        self.assertEqual(event.event_type, 1)
        self.assertEqual(event.text, "")

    def test_csi_u_alternates(self):
        event = self.key(b"\x1b[97:65u")
        self.assertEqual((event.code, event.shifted, event.base), (97, 65, 0))
        event = self.key(b"\x1b[97:65:97u")
        self.assertEqual((event.code, event.shifted, event.base), (97, 65, 97))
        # an empty shifted section must not shift the base section:
        event = self.key(b"\x1b[97::97u")
        self.assertEqual((event.code, event.shifted, event.base), (97, 0, 97))

    def test_csi_u_modifiers(self):
        # the wire value is 1 + the bits:
        for wire, bits in ((1, 0), (2, 1), (3, 2), (5, 4), (9, 8), (17, 16), (33, 32), (65, 64), (129, 128)):
            event = self.key(b"\x1b[97;%iu" % wire)
            self.assertEqual(event.mods, bits, f"wrong modifiers for wire value {wire}")

    def test_csi_u_event_types(self):
        for event_type in (1, 2, 3):
            event = self.key(b"\x1b[97;1:%iu" % event_type)
            self.assertEqual(event.event_type, event_type)
        # no event type section at all is a press:
        self.assertEqual(self.key(b"\x1b[97;1u").event_type, 1)
        # so is an out of range one:
        self.assertEqual(self.key(b"\x1b[97;1:9u").event_type, 1)

    def test_csi_u_text(self):
        self.assertEqual(self.key(b"\x1b[97;1;97u").text, "a")
        self.assertEqual(self.key(b"\x1b[97;1;104:105u").text, "hi")
        self.assertEqual(self.key(b"\x1b[97;1;9731u").text, "☃")
        # the terminal omits the default modifier group: `CSI <code> ; ; <text> u`
        event = self.key(b"\x1b[97;;97u")
        self.assertEqual(event.text, "a")
        self.assertEqual(event.mods, 0)
        self.assertEqual(event.event_type, 1)
        # shift + `a` as reported with both the alternate key and the associated text:
        event = self.key(b"\x1b[97:65;2;65u")
        self.assertEqual((event.code, event.shifted, event.mods, event.text), (97, 65, 1, "A"))
        # an empty text group leaves the text empty:
        self.assertEqual(self.key(b"\x1b[97;2;u").text, "")

    def test_csi_u_all_sections(self):
        event = self.key(b"\x1b[97:65:97;5:2;65u")
        self.assertEqual(event.code, 97)
        self.assertEqual(event.shifted, 65)
        self.assertEqual(event.base, 97)
        self.assertEqual(event.mods, 4)
        self.assertEqual(event.event_type, 2)
        self.assertEqual(event.text, "A")

    def test_csi_u_pua_keys(self):
        # the modifier keys and the ISO level shifts are only ever reported as `CSI u`:
        for code in tuple(range(57441, 57455)) + (57358, 57360, 57376, 57399):
            event = self.key(b"\x1b[%i;1u" % code)
            self.assertEqual(event.code, code)
            self.assertEqual(event.event_type, 1)

    def test_functional_letters(self):
        expected = {
            b"A": 57352, b"B": 57353, b"C": 57351, b"D": 57350,
            b"E": 57427, b"F": 57357, b"H": 57356,
            b"P": 57364, b"Q": 57365, b"S": 57367,
        }
        for letter, code in expected.items():
            self.assertEqual(self.key(b"\x1b[" + letter).code, code, f"CSI {letter!r}")
            # the same key with modifiers and an event type:
            event = self.key(b"\x1b[1;6:3" + letter)
            self.assertEqual(event.code, code)
            self.assertEqual(event.mods, 5)
            self.assertEqual(event.event_type, 3)

    def test_functional_numbers(self):
        expected = {
            1: 57356, 2: 57348, 3: 57349, 4: 57357, 5: 57354, 6: 57355, 7: 57356, 8: 57357,
            11: 57364, 12: 57365, 13: 57366, 14: 57367, 15: 57368,
            17: 57369, 18: 57370, 19: 57371, 20: 57372, 21: 57373, 23: 57374, 24: 57375,
            29: 57363,
        }
        for number, code in expected.items():
            self.assertEqual(self.key(b"\x1b[%i~" % number).code, code, f"CSI {number}~")
            event = self.key(b"\x1b[%i;3~" % number)
            self.assertEqual(event.code, code)
            self.assertEqual(event.mods, 2)

    def test_ss3(self):
        expected = {
            b"P": 57364, b"Q": 57365, b"R": 57366, b"S": 57367,
            b"A": 57352, b"B": 57353, b"C": 57351, b"D": 57350,
            b"E": 57427, b"F": 57357, b"H": 57356, b"M": 57414,
        }
        for letter, code in expected.items():
            self.assertEqual(self.key(b"\x1bO" + letter).code, code, f"SS3 {letter!r}")
        # an unknown SS3 is skipped whole:
        self.assertEqual(self.parse(b"\x1bOZa"), self.parse(b"a"))

    def test_legacy_printable(self):
        event = self.key(b"a")
        self.assertEqual(event.code, 97)
        self.assertEqual(event.text, "a")
        self.assertEqual(event.mods, 0)
        event = self.key("é".encode())
        self.assertEqual(event.code, 0xE9)
        self.assertEqual(event.text, "é")
        event = self.key("☃".encode())
        self.assertEqual(event.code, 0x2603)
        self.assertEqual(event.text, "☃")

    def test_legacy_alt(self):
        event = self.key(b"\x1ba")
        self.assertEqual(event.code, 97)
        self.assertEqual(event.mods, terminal_input.MOD_ALT)
        # alt + ctrl + `c`:
        event = self.key(b"\x1b\x03")
        self.assertEqual(event.code, 99)
        self.assertEqual(event.mods, terminal_input.MOD_ALT | terminal_input.MOD_CTRL)

    def test_legacy_controls(self):
        self.assertEqual(self.key(b"\r").code, 13)
        self.assertEqual(self.key(b"\t").code, 9)
        self.assertEqual(self.key(b"\x7f").code, 127)
        self.assertEqual(self.key(b"\x08").code, 127)
        for byte, code in ((b"\x01", 97), (b"\x03", 99), (b"\x1a", 122)):
            event = self.key(byte)
            self.assertEqual(event.code, code)
            self.assertEqual(event.mods, terminal_input.MOD_CTRL)
            self.assertEqual(event.text, "")
        for byte, code in ((b"\x00", 64), (b"\x1c", 92), (b"\x1f", 95)):
            event = self.key(byte)
            self.assertEqual(event.code, code)
            self.assertEqual(event.mods, terminal_input.MOD_CTRL)

    def test_bare_escape_stays_buffered(self):
        parser = terminal_input.InputParser()
        self.assertEqual(parser.feed(b"\x1b"), [])
        # only a `flush` turns it into an `Escape` key press:
        events = parser.flush()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].code, 27)
        self.assertEqual(events[0].event_type, 1)
        self.assertEqual(parser.flush(), [])

    def test_flush_drops_a_partial_sequence(self):
        # a sequence split by a stall in the byte stream must not be typed into the
        # focused window one parameter byte at a time:
        for partial in (b"\x1b[97;1", b"\x1b[<0;100", b"\x1b[1;5", b"\x1b[97:65;2;6",
                        b"\x1b_Gi=3;O", b"\x1b]52;c;QUJ", b"\x1bP1$r0", b"\x1b[3"):
            parser = terminal_input.InputParser()
            self.assertEqual(parser.feed(partial), [], f"{partial!r} should stay buffered")
            self.assertEqual(parser.pending, len(partial))
            self.assertEqual(parser.flush(), [], f"{partial!r} should be dropped, not decoded")
            self.assertEqual(parser.pending, 0)
            self.assertEqual(parser.flush(), [])

    def test_legacy_alt_never_needs_a_flush(self):
        # `ESC` + a byte which cannot start a longer sequence is `alt` + that key,
        # and it is complete as soon as it arrives:
        for data, code in ((b"\x1ba", 97), (b"\x1b1", 49), (b"\x1b.", 46)):
            parser = terminal_input.InputParser()
            events = parser.feed(data)
            self.assertEqual(len(events), 1, f"{data!r}")
            self.assertEqual(events[0].code, code)
            self.assertEqual(events[0].mods, terminal_input.MOD_ALT)
            self.assertEqual(parser.pending, 0)

    def test_flush_drops_a_truncated_sequence_start(self):
        # `ESC` + a byte which does start a longer sequence is ambiguous: a truncated
        # sequence, or `alt` + that key on a terminal which does not use the kitty protocol.
        # it is dropped rather than typed, since the kitty protocol reports those keys as `CSI u`
        for data in (b"\x1b[", b"\x1b]", b"\x1b_", b"\x1bP", b"\x1b^", b"\x1bX", b"\x1bO"):
            parser = terminal_input.InputParser()
            self.assertEqual(parser.feed(data), [])
            self.assertEqual(parser.flush(), [], f"{data!r} should be dropped")
            self.assertEqual(parser.pending, 0)
        # so is a truncated utf8 character:
        parser = terminal_input.InputParser()
        self.assertEqual(parser.feed("é".encode()[:1]), [])
        self.assertEqual(parser.flush(), [])

    def test_flush_after_complete_events(self):
        # what arrived whole before the truncated tail is still reported:
        parser = terminal_input.InputParser()
        events = parser.feed(b"\x1b[97u\x1b[<0;10")
        self.assertEqual([event.code for event in events], [97])
        self.assertEqual(parser.flush(), [])

    def test_escape_then_more(self):
        parser = terminal_input.InputParser()
        self.assertEqual(parser.feed(b"\x1b"), [])
        events = parser.feed(b"[A")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].code, 57352)

    def test_double_escape(self):
        events = self.parse(b"\x1b\x1b[A")
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].code, 27)
        self.assertEqual(events[1].code, 57352)

    def test_keyboard_flags_response(self):
        event = self.one(b"\x1b[?15u")
        self.assertIsInstance(event, terminal_input.KeyboardFlagsResponse)
        self.assertEqual(event.flags, 15)
        self.assertEqual(self.one(b"\x1b[?0u").flags, 0)

    def test_graphics_response(self):
        event = self.one(b"\x1b_Gi=3;OK\x1b\\")
        self.assertIsInstance(event, terminal_input.GraphicsResponse)
        self.assertEqual(event.image_id, 3)
        self.assertTrue(event.ok)
        self.assertEqual(event.message, "OK")
        event = self.one(b"\x1b_Gi=7,p=2;ENOENT:no such file\x1b\\")
        self.assertEqual(event.image_id, 7)
        self.assertFalse(event.ok)
        self.assertEqual(event.message, "ENOENT:no such file")
        # an APC that is not a graphics answer is skipped:
        self.assertEqual(self.parse(b"\x1b_Zwhatever\x1b\\a"), self.parse(b"a"))

    def test_text_report(self):
        event = self.one(b"\x1b[4;600;800t")
        self.assertIsInstance(event, terminal_input.TextReport)
        self.assertEqual(event.kind, 4)
        self.assertEqual(event.values, (600, 800))
        event = self.one(b"\x1b[6;20;10t")
        self.assertEqual(event.kind, 6)
        self.assertEqual(event.values, (20, 10))

    def test_skipped_strings(self):
        # OSC (BEL terminated and ST terminated), DCS and PM must not become key events:
        for data in (b"\x1b]52;c;QUJD\x07", b"\x1b]11;rgb:0/0/0\x1b\\",
                     b"\x1bP1$r0m\x1b\\", b"\x1b^private\x1b\\"):
            self.assertEqual(self.parse(data), [], f"{data!r} should be skipped")
            self.assertEqual(self.parse(data + b"a"), self.parse(b"a"))

    def test_malformed_does_not_raise(self):
        for data in (b"\x1b[", b"\x1b[;;;;", b"\x1b[999999999999999u", b"\x1b[<1;2M",
                     b"\x1b[<a;b;cM", b"\x1b[u", b"\x1b[:::u", b"\x1b[~", b"\x1b[99~",
                     b"\x1b[ Q", b"\x1b_\x1b\\", b"\xff\xfe", b"\x1b[>1;2c"):
            self.parse(data)

    def test_malformed_does_not_swallow(self):
        # an escape sequence aborted by the start of a valid one must not eat it:
        events = self.parse(b"\x1b[1;2\x1b[B")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].code, 57353)
        # an unknown final byte only costs its own sequence:
        events = self.parse(b"\x1b[999Xa")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].code, 97)
        # an invalid utf8 byte only costs itself:
        events = self.parse(b"\xffa")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].code, 97)
        # a truncated utf8 sequence resynchronizes on the next byte:
        events = self.parse(b"\xc3Za")
        self.assertEqual([event.code for event in events], [90, 97])

    def test_unterminated_sequences_give_up(self):
        # a terminal that never terminates a sequence must not make us buffer forever:
        oversized = terminal_input.MAX_ESCAPE + 1000
        for data in (b"\x1b_G" + b"x" * oversized, b"\x1b[" + b"1" * oversized,
                     b"\x1b]11;" + b"x" * oversized):
            parser = terminal_input.InputParser()
            events = parser.feed(data)
            self.assertEqual(parser.flush(), [], f"{len(data)} bytes should not stay buffered")
            self.assertEqual(parser.pending, 0)
            # giving up consumes the bytes already scanned rather than decoding them as keys:
            self.assertLess(len(events), 1100, f"{len(events)} events from {len(data)} bytes")

    def test_split_utf8(self):
        parser = terminal_input.InputParser()
        self.assertEqual(parser.feed("☃".encode()[:2]), [])
        events = parser.feed("☃".encode()[2:])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].code, 0x2603)

    def test_incremental_equivalence(self):
        data = b"".join(CORPUS)
        whole = terminal_input.InputParser().feed(data)
        self.assertTrue(whole, "the corpus should produce events")
        parser = terminal_input.InputParser()
        one_at_a_time = []
        for i in range(len(data)):
            one_at_a_time += parser.feed(data[i:i + 1])
        self.assertEqual([repr(e) for e in whole], [repr(e) for e in one_at_a_time])
        self.assertEqual(whole, one_at_a_time)

    def test_every_split_point(self):
        data = b"".join(CORPUS)
        whole = terminal_input.InputParser().feed(data)
        for split in range(len(data) + 1):
            parser = terminal_input.InputParser()
            events = parser.feed(data[:split])
            events += parser.feed(data[split:])
            self.assertEqual(events, whole, f"mismatch when splitting at {split}")


@unittest.skipIf(terminal_keys is None, "the terminal client component is not built")
class TerminalKeysTest(unittest.TestCase):

    def test_functional_keysyms(self):
        expected = {
            27: "Escape", 13: "Return", 9: "Tab", 127: "BackSpace",
            57344: "Escape", 57345: "Return", 57346: "Tab", 57347: "BackSpace",
            57348: "Insert", 57349: "Delete",
            57350: "Left", 57351: "Right", 57352: "Up", 57353: "Down",
            57354: "Page_Up", 57355: "Page_Down", 57356: "Home", 57357: "End",
            57358: "Caps_Lock", 57359: "Scroll_Lock", 57360: "Num_Lock",
            57361: "Print", 57362: "Pause", 57363: "Menu",
        }
        for code, keysym in expected.items():
            self.assertEqual(terminal_keys.keysym_name_for(code, ""), keysym, f"code {code}")

    def test_function_keysyms(self):
        for i in range(1, 13):
            self.assertEqual(terminal_keys.keysym_name_for(57363 + i, ""), f"F{i}")
        self.assertEqual(terminal_keys.keysym_name_for(57376, ""), "F13")
        self.assertEqual(terminal_keys.keysym_name_for(57398, ""), "F35")

    def test_keypad_keysyms(self):
        for i in range(10):
            self.assertEqual(terminal_keys.keysym_name_for(57399 + i, ""), f"KP_{i}")
        expected = {
            57409: "KP_Decimal", 57410: "KP_Divide", 57411: "KP_Multiply",
            57412: "KP_Subtract", 57413: "KP_Add", 57414: "KP_Enter", 57415: "KP_Equal",
            57416: "KP_Separator", 57417: "KP_Left", 57418: "KP_Right", 57419: "KP_Up",
            57420: "KP_Down", 57421: "KP_Page_Up", 57422: "KP_Page_Down",
            57423: "KP_Home", 57424: "KP_End", 57425: "KP_Insert", 57426: "KP_Delete",
            57427: "KP_Begin",
        }
        for code, keysym in expected.items():
            self.assertEqual(terminal_keys.keysym_name_for(code, ""), keysym, f"code {code}")

    def test_modifier_keysyms(self):
        expected = (
            "Shift_L", "Control_L", "Alt_L", "Super_L", "Hyper_L", "Meta_L",
            "Shift_R", "Control_R", "Alt_R", "Super_R", "Hyper_R", "Meta_R",
        )
        for i, keysym in enumerate(expected):
            self.assertEqual(terminal_keys.keysym_name_for(57441 + i, ""), keysym)
        self.assertEqual(terminal_keys.keysym_name_for(57453, ""), "ISO_Level3_Shift")
        self.assertEqual(terminal_keys.keysym_name_for(57454, ""), "ISO_Level3_Shift")

    def test_printable_keysyms(self):
        self.assertEqual(terminal_keys.keysym_name_for(97, "a"), "a")
        self.assertEqual(terminal_keys.keysym_name_for(97, ""), "a")
        self.assertEqual(terminal_keys.keysym_name_for(97, "A"), "A")
        self.assertEqual(terminal_keys.keysym_name_for(0x40, "@"), "at")
        self.assertEqual(terminal_keys.keysym_name_for(0x20, " "), "space")
        self.assertEqual(terminal_keys.keysym_name_for(0x20, ""), "space")
        self.assertEqual(terminal_keys.keysym_name_for(0xE9, ""), "eacute")
        self.assertEqual(terminal_keys.keysym_name_for(0x2603, ""), "U2603")
        self.assertEqual(terminal_keys.keysym_name_for(0, ""), "")

    def test_modifier_names(self):
        expected = {
            0: [],
            1: ["shift"],
            2: ["mod1"],
            4: ["control"],
            8: ["mod3"],
            16: ["mod4"],
            32: ["mod1"],
            64: ["lock"],
            128: ["mod2"],
        }
        for bits, names in expected.items():
            self.assertEqual(terminal_keys.modifier_names(bits), names, f"bits {bits}")

    def test_modifier_names_combinations(self):
        # always in the canonical order: shift, lock, control, mod1..mod5
        self.assertEqual(terminal_keys.modifier_names(1 | 4), ["shift", "control"])
        self.assertEqual(terminal_keys.modifier_names(4 | 1), ["shift", "control"])
        self.assertEqual(terminal_keys.modifier_names(1 | 2 | 4), ["shift", "control", "mod1"])
        self.assertEqual(terminal_keys.modifier_names(64 | 128), ["lock", "mod2"])
        self.assertEqual(terminal_keys.modifier_names(8 | 16), ["mod3", "mod4"])
        # alt and meta are both `mod1` and must not be listed twice:
        self.assertEqual(terminal_keys.modifier_names(2 | 32), ["mod1"])
        self.assertEqual(terminal_keys.modifier_names(255),
                         ["shift", "lock", "control", "mod1", "mod2", "mod3", "mod4"])

    def test_modifier_names_from_mouse_event(self):
        # the mouse parser reports the same modifier bits:
        events = terminal_input.InputParser().feed(b"\x1b[<28;1;2M")
        self.assertEqual(terminal_keys.modifier_names(events[0].mods), ["shift", "control", "mod1"])

    def test_make_key_event(self):
        ev = terminal_input.KeyEvent(code=97, mods=4, event_type=1, text="")
        key_event = terminal_keys.make_key_event(ev)
        self.assertEqual(key_event.keyname, "a")
        self.assertTrue(key_event.pressed)
        self.assertEqual(key_event.modifiers, ["control"])
        self.assertEqual(key_event.string, "")
        self.assertEqual(key_event.keyval, 97)
        self.assertEqual(key_event.keycode, 0)
        self.assertEqual(key_event.group, 0)

    def test_make_key_event_types(self):
        for event_type, pressed in ((1, True), (2, True), (3, False)):
            ev = terminal_input.KeyEvent(code=97, event_type=event_type, text="a")
            self.assertEqual(terminal_keys.make_key_event(ev).pressed, pressed)

    def test_make_key_event_functional(self):
        ev = terminal_input.KeyEvent(code=57352, mods=1)
        key_event = terminal_keys.make_key_event(ev)
        self.assertEqual(key_event.keyname, "Up")
        self.assertEqual(key_event.modifiers, ["shift"])
        self.assertEqual(key_event.keyval, 0)
        self.assertEqual(key_event.string, "")
        for code, keyname in ((27, "Escape"), (13, "Return"), (9, "Tab"), (127, "BackSpace"),
                              (57443, "Alt_L"), (57453, "ISO_Level3_Shift")):
            key_event = terminal_keys.make_key_event(terminal_input.KeyEvent(code=code))
            self.assertEqual(key_event.keyname, keyname)
            self.assertEqual(key_event.keyval, 0)

    def test_make_key_event_text(self):
        ev = terminal_input.KeyEvent(code=97, shifted=65, mods=1, text="A")
        key_event = terminal_keys.make_key_event(ev)
        self.assertEqual(key_event.keyname, "A")
        self.assertEqual(key_event.string, "A")
        self.assertEqual(key_event.keyval, 65)
        self.assertEqual(key_event.modifiers, ["shift"])

    def test_key_text(self):
        # the associated text wins when the terminal reports it:
        self.assertEqual(terminal_keys.key_text(
            terminal_input.KeyEvent(code=97, shifted=65, mods=1, text="A")), "A")
        # a key release carries no text, so the alternate shifted key is used instead:
        self.assertEqual(terminal_keys.key_text(
            terminal_input.KeyEvent(code=97, shifted=65, mods=1, event_type=3)), "A")
        # without shift the alternate key is not what the key produced:
        self.assertEqual(terminal_keys.key_text(
            terminal_input.KeyEvent(code=97, shifted=65)), "")
        # nothing to fall back on:
        self.assertEqual(terminal_keys.key_text(terminal_input.KeyEvent(code=97, mods=1)), "")
        # a functional key is named by its code, never by an alternate code point:
        self.assertEqual(terminal_keys.key_text(
            terminal_input.KeyEvent(code=57352, shifted=57352, mods=1)), "")
        # and neither is a control character:
        self.assertEqual(terminal_keys.key_text(
            terminal_input.KeyEvent(code=97, shifted=1, mods=1)), "")

    def test_make_key_event_shifted(self):
        # the kitty `unicode-key-code` is the unshifted key: reporting `a` with the `shift`
        # modifier makes the server type `a`, so the shifted code point must be used
        for code, shifted, keyname, string in (
            (97, 65, "A", "A"),
            (50, 64, "at", "@"),
            (59, 58, "colon", ":"),
            (47, 63, "question", "?"),
        ):
            ev = terminal_input.KeyEvent(code=code, shifted=shifted, mods=1)
            key_event = terminal_keys.make_key_event(ev)
            self.assertEqual(key_event.keyname, keyname, f"code {code}")
            self.assertEqual(key_event.string, string, f"code {code}")
            self.assertEqual(key_event.keyval, shifted, f"code {code}")
            self.assertEqual(key_event.modifiers, ["shift"])

    def test_make_key_event_shifted_from_parser(self):
        # what kitty sends for shift + `a` with the "report alternate keys" flag only,
        # and with the "report associated text" flag as well:
        for data in (b"\x1b[97:65;2u", b"\x1b[97:65;2;65u"):
            events = terminal_input.InputParser().feed(data)
            self.assertEqual(len(events), 1)
            key_event = terminal_keys.make_key_event(events[0])
            self.assertEqual(key_event.keyname, "A", data)
            self.assertEqual(key_event.string, "A", data)
            self.assertEqual(key_event.modifiers, ["shift"], data)
        # the matching release (which never carries any text) must name the same key:
        events = terminal_input.InputParser().feed(b"\x1b[97:65;2:3u")
        key_event = terminal_keys.make_key_event(events[0])
        self.assertEqual(key_event.keyname, "A")
        self.assertFalse(key_event.pressed)
        # ctrl + shift + `a` keeps both modifiers:
        events = terminal_input.InputParser().feed(b"\x1b[97:65;6u")
        key_event = terminal_keys.make_key_event(events[0])
        self.assertEqual(key_event.keyname, "A")
        self.assertEqual(key_event.modifiers, ["shift", "control"])

    def test_make_key_event_unshifted_is_unchanged(self):
        events = terminal_input.InputParser().feed(b"\x1b[97;1;97u")
        key_event = terminal_keys.make_key_event(events[0])
        self.assertEqual(key_event.keyname, "a")
        self.assertEqual(key_event.string, "a")
        self.assertEqual(key_event.keyval, 97)
        self.assertEqual(key_event.modifiers, [])
        # a legacy (non kitty protocol) key is unaffected:
        events = terminal_input.InputParser().feed(b"a")
        key_event = terminal_keys.make_key_event(events[0])
        self.assertEqual((key_event.keyname, key_event.string, key_event.keyval), ("a", "a", 97))

    def test_make_key_event_from_parser(self):
        events = terminal_input.InputParser().feed(b"\x1b[27u\x1b[57441;1:3u\x1ba")
        self.assertEqual(len(events), 3)
        escape, shift, alt_a = (terminal_keys.make_key_event(event) for event in events)
        self.assertEqual(escape.keyname, "Escape")
        self.assertTrue(escape.pressed)
        self.assertEqual(shift.keyname, "Shift_L")
        self.assertFalse(shift.pressed)
        self.assertEqual(alt_a.keyname, "a")
        self.assertEqual(alt_a.modifiers, ["mod1"])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
